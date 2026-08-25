import 'dart:async';
import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:web_socket_channel/io.dart';

import 'dart:math';

import '../models.dart';
import '../store.dart';
import 'api_client.dart';
import 'app_config.dart';
import 'contract.dart';

/// Production-mode gateway to the Ecolamp backend.
///
/// Responsibilities:
/// - real authentication (JWT in the device secure store, never prefs)
/// - syncing AUTHORITATIVE user/points/history into the display [AppStore]
///   so every existing screen renders backend truth unchanged
/// - the deposit lifecycle: mint handoff QR token, watch live status
///   (WebSocket first, polling fallback), and reconcile the terminal result
///
/// The gateway NEVER awards points. Points only ever arrive from the
/// backend's serialized deposit / user payload.
class BackendGateway {
  BackendGateway._()
    : api = ApiClient(AppConfig.apiBaseUrl),
      _storage = const FlutterSecureStorage();

  static final BackendGateway instance = BackendGateway._();

  final ApiClient api;
  final FlutterSecureStorage _storage;

  static const _tokenKey = 'ecolamp_session_token';
  static const _emailKey = 'ecolamp_session_email';

  bool _tokenAttached = false;

  // ---------------------------------------------------------------------------
  // Auth (POST /auth/login, GET /auth/me, POST /auth/logout)
  // ---------------------------------------------------------------------------

  /// Restores a persisted session at app start. Returns true when a valid
  /// backend session exists; on 401 the stale token is dropped silently.
  Future<bool> restoreSession() async {
    final token = await _storage.read(key: _tokenKey);
    if (token == null || token.isEmpty) return false;
    api.setToken(token);
    try {
      final me = await api.get('/auth/me');
      final wireUser = me['user'] as Map<String, dynamic>;
      final email = await _storage.read(key: _emailKey);
      await _applyBackendSession(wireUser, fallbackEmail: email);
      _tokenAttached = true;
      return true;
    } on ApiException catch (e) {
      if (e.isUnauthorized) {
        await _storage.delete(key: _tokenKey);
        api.setToken(null);
      }
      return false;
    } catch (_) {
      // Offline: keep the token and let the next call retry.
      _tokenAttached = false;
      return false;
    }
  }

  /// Real login against POST /auth/login. Throws [ApiException] with a
  /// user-safe message on failure.
  Future<void> login({required String email, required String password}) async {
    final body = await api.post(
      '/auth/login',
      data: {'email': email, 'password': password},
    );
    final wireUser = body['user'] as Map<String, dynamic>;
    await _persistToken((body['token'] as String?) ?? '');
    await _applyBackendSession(wireUser, fallbackEmail: email);
  }

  /// Account creation via POST /auth/register. The backend deliberately does
  /// NOT authenticate on register — the caller must follow with [login].
  Future<void> signup({
    required String name,
    required String email,
    required String studentId,
    required String password,
    String facultyId = 'ENGINEERING',
  }) async {
    await api.post(
      '/auth/register',
      data: {
        'name': name,
        'email': email,
        'password': password,
        'studentCode': studentId,
        'facultyId': facultyId,
      },
    );
  }

  Future<void> logout() async {
    try {
      await api.post('/auth/logout');
    } catch (_) {
      // Server offline: local logout must still succeed.
    }
    await _clearLocalUserData();
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _emailKey);
    api.setToken(null);
  }

  // ---------------------------------------------------------------------------
  // Authoritative sync → AppStore (display mirror of backend truth)
  // ---------------------------------------------------------------------------

  /// Pulls /users/me + /waste/history and mirrors them into [AppStore].
  /// Called after login, after a completed deposit, and on pull-to-refresh.
  Future<void> syncFromBackend() async {
    final me = await api.get('/users/me');
    final wireUser = me['user'] as Map<String, dynamic>;
    final email = await _storage.read(key: _emailKey);
    await _applyBackendSession(wireUser, fallbackEmail: email);

    final history = await api.get('/waste/history');
    final items = contributionsFromHistoryWire(
      (history['items'] as List<dynamic>? ?? const []),
    );
    await AppStore.instance.replaceFromBackend(
      user: AppStore.instance.user,
      points: pointsFromWire(wireUser),
      contributions: items,
    );
  }

  Future<List<Station>> fetchStations() async {
    final body = await api.get('/stations');
    return stationsFromWire(body['items'] as List<dynamic>? ?? const []);
  }

  Future<List<LeaderboardEntry>> fetchFacultyLeaderboard() async {
    final body = await api.get('/leaderboard/faculties');
    return leaderboardFromWire(body['entries'] as List<dynamic>? ?? const []);
  }

  // ---------------------------------------------------------------------------
  // Rewards (production): the backend catalog is authoritative and the
  // deduction happens server-side in one atomic transaction. The client
  // only displays the returned balance.
  // ---------------------------------------------------------------------------

  /// GET /rewards -> the live catalog plus the authoritative balance.
  Future<({int balance, List<BackendReward> rewards})> fetchRewards() async {
    final body = await api.get('/rewards');
    return (
      balance: (body['balance'] as num?)?.toInt() ?? 0,
      rewards: rewardsFromWire(body['rewards'] as List<dynamic>? ?? const []),
    );
  }

  /// POST /rewards/{id}/redeem — idempotent via a client-generated key.
  /// Returns the backend's post-redemption balance. Throws [ApiException]
  /// (409) when the balance is insufficient or the reward is unavailable.
  Future<int> redeemReward({
    required String rewardId,
    String? destination,
  }) async {
    final body = await api.post(
      '/rewards/$rewardId/redeem',
      data: {
        'idempotency_key': _idempotencyKey(),
        if (destination != null && destination.isNotEmpty)
          'destination': destination,
      },
    );
    return (body['balance'] as num?)?.toInt() ?? 0;
  }

  /// POST /rewards/redemptions/{id}/cancel — refunds an unused code.
  Future<int> cancelRedemption(String redemptionId) async {
    final body = await api.post('/rewards/redemptions/$redemptionId/cancel');
    return (body['balance'] as num?)?.toInt() ?? pointsFromWire(body);
  }

  /// Client-generated idempotency key (no double-spend on retry).
  String _idempotencyKey() {
    final rnd = Random.secure();
    final ts = DateTime.now().microsecondsSinceEpoch.toRadixString(36);
    final rand = List.generate(
      4,
      (_) => rnd.nextInt(0xFFFFFFFF).toRadixString(36).padLeft(7, '0'),
    ).join();
    return 'eco-$ts-$rand';
  }

  // ---------------------------------------------------------------------------
  // Deposit flow (handoff QR → station claim → live status → terminal)
  // ---------------------------------------------------------------------------

  /// Mints the short-lived single-use handoff token rendered as the
  /// student's dynamic QR. The STATION tablet scans it and calls
  /// `POST /deposit/session/claim` with its station key.
  Future<({String token, DateTime expiresAt})> mintHandoffToken() async {
    final body = await api.post('/deposit/handoff-token');
    return (
      token: body['token'] as String,
      expiresAt:
          DateTime.tryParse(body['expires_at'] as String? ?? '') ??
          DateTime.now().add(const Duration(seconds: 120)),
    );
  }

  /// The QR payload shown on screen. Contains ONLY the short-lived single-use
  /// token — never a long-lived credential.
  static String handoffQrPayload(String token) => 'ECOLOOP:HANDOFF:$token';

  /// Finds the student's current non-terminal deposit session, if any.
  Future<WireDeposit?> activeOperation() async {
    try {
      final body = await api.get('/deposit/active');
      final dep = body['deposit'];
      if (dep is Map<String, dynamic>) return WireDeposit.fromJson(dep);
      return null;
    } on ApiException catch (e) {
      if (e.statusCode == 404) return null;
      rethrow;
    }
  }

  /// Watches an operation until a terminal state, forwarding live phases.
  /// WebSocket first (transport only — it carries persisted state), then
  /// transparent HTTP-polling fallback. Reconnects are absorbed by falling
  /// back to polling; the terminal snapshot is always authoritative.
  Future<WireDeposit> watchOperation(
    String operationId, {
    void Function(WireDeposit live)? onLive,
    Duration pollInterval = const Duration(seconds: 2),
    Duration timeout = const Duration(minutes: 3),
  }) async {
    final token = api.token;
    if (token != null) {
      try {
        return await _watchViaSocket(operationId, token, onLive, timeout);
      } catch (_) {
        // fall through to polling
      }
    }
    return _watchViaPolling(operationId, onLive, pollInterval, timeout);
  }

  Future<WireDeposit> _watchViaSocket(
    String operationId,
    String token,
    void Function(WireDeposit)? onLive,
    Duration timeout,
  ) async {
    final base = Uri.parse(api.baseUrl);
    final uri = Uri(
      scheme: base.scheme == 'https' ? 'wss' : 'ws',
      host: base.host,
      port: base.port,
      path: '/ws/deposits/$operationId',
      queryParameters: {'token': token},
    );
    final channel = IOWebSocketChannel.connect(uri);
    try {
      await for (final frame in channel.stream.timeout(timeout)) {
        final message = jsonDecode(frame as String) as Map<String, dynamic>;
        final type = message['type'] as String?;
        if (type == 'keepalive') continue;
        if (type != 'state' && type != 'terminal') continue;
        final deposit = WireDeposit.fromJson(
          message['deposit'] as Map<String, dynamic>,
        );
        if (deposit.isTerminal) return deposit;
        onLive?.call(deposit);
      }
    } finally {
      await channel.sink.close();
    }
    throw const ApiException(
      'The station did not respond in time. Please retry.',
    );
  }

  Future<WireDeposit> _watchViaPolling(
    String operationId,
    void Function(WireDeposit)? onLive,
    Duration interval,
    Duration timeout,
  ) async {
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      final body = await api.get('/deposit/$operationId');
      final deposit = WireDeposit.fromJson(body);
      if (deposit.isTerminal) return deposit;
      onLive?.call(deposit);
      await Future<void>.delayed(interval);
    }
    throw const ApiException(
      'The station did not respond in time. Please retry.',
    );
  }

  /// Cancels a live operation (POST /deposit/{id}/cancel).
  Future<WireDeposit> cancelOperation(String operationId) async {
    final body = await api.post('/deposit/$operationId/cancel');
    return WireDeposit.fromJson(body);
  }

  // ---------------------------------------------------------------------------
  // internals
  // ---------------------------------------------------------------------------

  Future<void> _applyBackendSession(
    Map<String, dynamic> wireUser, {
    String? fallbackEmail,
  }) async {
    final user = userFromWire(wireUser, fallbackEmail: fallbackEmail);
    if (!_tokenAttached || AppStore.instance.user?.email != user.email) {
      await AppStore.instance.setBackendUser(
        user,
        points: pointsFromWire(wireUser),
      );
    } else {
      await AppStore.instance.setBackendUser(
        user,
        points: pointsFromWire(wireUser),
      );
    }
  }

  Future<void> _persistToken(String token) async {
    await _storage.write(key: _tokenKey, value: token);
    api.setToken(token.isEmpty ? null : token);
    _tokenAttached = token.isNotEmpty;
  }

  Future<void> _clearLocalUserData() => AppStore.instance.logout();
}
