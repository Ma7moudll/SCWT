import 'dart:convert';
import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

import 'models.dart';

class UserAccount {
  const UserAccount({
    required this.name,
    required this.email,
    required this.studentId,
  });
  final String name;
  final String email;
  final String studentId;

  String get initials {
    final parts = name.trim().split(RegExp(r'\s+'))
      ..removeWhere((p) => p.isEmpty);
    if (parts.isEmpty) return '?';
    if (parts.length == 1) return parts.first[0].toUpperCase();
    return (parts.first[0] + parts.last[0]).toUpperCase();
  }

  String get firstName => name.trim().split(' ').first;

  Map<String, Object?> toJson() => {
    'name': name,
    'email': email,
    'studentId': studentId,
  };

  factory UserAccount.fromJson(Map<String, dynamic> j) => UserAccount(
    name: j['name'] as String,
    email: j['email'] as String,
    studentId: j['studentId'] as String,
  );
}

/// Result of a reward redemption attempt.
enum RedeemResult { success, insufficientPoints }

class AppStore {
  AppStore._();
  static final AppStore instance = AppStore._();

  /// Creates an independent store instance that reads the same persisted
  /// state from disk. Used by tests to simulate an app restart.
  static AppStore freshForTest() => AppStore._();

  static const _userKey = 'session_user';
  static const _loggedInKey = 'logged_in';
  static const _pointsKey = 'points';
  static const _contributionsKey = 'contributions';
  static const _collectionsKey = 'collections';
  static const _notificationsKey = 'notifications';
  static const _redemptionsKey = 'redemptions';

  // A brand-new account starts at ZERO points with an EMPTY history. Points
  // are awarded only for verified deposits. (Backend will be authoritative.)
  int _points = 0;
  UserAccount? _user;
  bool _loggedIn = false;
  bool _backendMode = false;
  List<Contribution> _contributions = [];
  List<CollectionRequest> _collectionRequests = [];
  List<AppNotification> _notifications = [];
  List<Map<String, Object?>> _redemptions = [];
  bool _loaded = false;

  // --- Recycling flow state (in-memory; the running session) ---
  Contribution? currentContribution;
  CollectionRequest? currentCollectionRequest;
  Faculty? currentFaculty;
  Station? currentStation;
  RecyclingSession? currentSession;

  int get points => _points;
  UserAccount? get user => _user;
  bool get isLoggedIn => _loggedIn;

  /// True when this store mirrors the Ecolamp backend (production
  /// mode). In backend mode the store NEVER awards points itself — it only
  /// displays what the backend persisted (see BackendGateway).
  bool get isBackendMode => _backendMode;

  List<Contribution> get contributions => List.unmodifiable(_contributions);
  List<CollectionRequest> get collectionRequests =>
      List.unmodifiable(_collectionRequests);
  List<AppNotification> get notifications => List.unmodifiable(_notifications);

  Future<void> ensureLoaded() async {
    if (_loaded) return;
    final p = await SharedPreferences.getInstance();
    _points = p.getInt(_pointsKey) ?? 0;
    _loggedIn = p.getBool(_loggedInKey) ?? false;
    final rawUser = p.getString(_userKey);
    if (rawUser != null) {
      _user = UserAccount.fromJson(jsonDecode(rawUser) as Map<String, dynamic>);
    }
    final rawContribs = p.getStringList(_contributionsKey);
    if (rawContribs != null) {
      _contributions = rawContribs
          .map(
            (e) => Contribution.fromJson(jsonDecode(e) as Map<String, dynamic>),
          )
          .toList();
    }
    final rawCollections = p.getStringList(_collectionsKey);
    if (rawCollections != null) {
      _collectionRequests = rawCollections
          .map(
            (e) => CollectionRequest.fromJson(
              jsonDecode(e) as Map<String, dynamic>,
            ),
          )
          .toList();
    }
    final rawNotifications = p.getStringList(_notificationsKey);
    if (rawNotifications != null) {
      _notifications = rawNotifications
          .map(
            (e) =>
                AppNotification.fromJson(jsonDecode(e) as Map<String, dynamic>),
          )
          .toList();
    }
    final rawRedemptions = p.getStringList(_redemptionsKey);
    if (rawRedemptions != null) {
      _redemptions = rawRedemptions
          .map(
            (e) => Map<String, Object?>.from(
              jsonDecode(e) as Map<String, dynamic>,
            ),
          )
          .toList();
    }
    _loaded = true;
  }

  // ---------------------------------------------------------------------------
  // Production-mode (backend-authoritative) hooks — used ONLY by the
  // BackendGateway. They never award points; they mirror backend truth.
  // ---------------------------------------------------------------------------

  /// Marks the store as a backend mirror and applies the authenticated user
  /// with their authoritative point balance.
  Future<void> setBackendUser(UserAccount user, {required int points}) async {
    _backendMode = true;
    _loggedIn = true;
    _user = user;
    _points = points < 0 ? 0 : points;
    await _persistUser();
    final p = await SharedPreferences.getInstance();
    await p.setInt(_pointsKey, _points);
  }

  /// Replaces the display state with an authoritative snapshot from
  /// GET /users/me + GET /waste/history.
  Future<void> replaceFromBackend({
    UserAccount? user,
    required int points,
    required List<Contribution> contributions,
  }) async {
    if (user != null) _user = user;
    _backendMode = true;
    _loggedIn = true;
    _points = points < 0 ? 0 : points;
    _contributions = List.of(contributions);
    await _persistUserData();
  }

  /// Production mode ONLY: records the backend-confirmed deposit for display
  /// (history + notification). Points are NOT computed here — the balance
  /// comes exclusively from the backend via [replaceFromBackend] / sync.
  Future<void> applyAuthoritativeDeposit(
    Contribution contribution, {
    String? stationName,
  }) async {
    currentContribution = contribution;
    _contributions.insert(0, contribution);
    _notifications.insert(
      0,
      AppNotification(
        id: 'n-${DateTime.now().millisecondsSinceEpoch}',
        title: contribution.points > 0
            ? 'You earned ${contribution.points} EcoPoints'
            : 'Deposit verified',
        body:
            '${contribution.materialType} verified at ${stationName ?? 'an Ecolamp station'}.',
        time: 'Just now',
        iconKey: 'eco',
      ),
    );
    await _persistUserData();
  }

  // ---------------------------------------------------------------------------
  // Authentication (local until POST /auth/login + POST /auth/signup exist)
  // ---------------------------------------------------------------------------

  Future<void> login({required String email}) async {
    // Local session: the account is derived from what the user signed in with.
    // A backend will replace this with a real credential check + token.
    final existing = _user;
    _user = existing?.email.toLowerCase() == email.toLowerCase()
        ? existing
        : UserAccount(
            name: existing?.name ?? _nameFromEmail(email),
            email: email,
            studentId: existing?.studentId ?? _studentIdFromEmail(email),
          );
    _loggedIn = true;
    await _persistUser();
  }

  Future<void> signup({
    required String name,
    required String email,
    required String studentId,
  }) async {
    _user = UserAccount(name: name, email: email, studentId: studentId);
    _loggedIn = true;
    await _persistUser();
  }

  String _nameFromEmail(String email) {
    final local = email
        .split('@')
        .first
        .replaceAll(RegExp(r'[._\-]+'), ' ')
        .trim();
    return local.isEmpty ? 'Recycler' : local;
  }

  String _studentIdFromEmail(String email) =>
      'ECO-${email.hashCode.abs().toString().substring(0, 4).padLeft(4, '0')}';

  Future<void> _persistUser() async {
    final p = await SharedPreferences.getInstance();
    await p.setBool(_loggedInKey, _loggedIn);
    final u = _user;
    if (u != null) await p.setString(_userKey, jsonEncode(u.toJson()));
  }

  /// Logs out: clears the session AND all per-user local data so no account
  /// data leaks into the next login on this device.
  Future<void> logout() async {
    _loggedIn = false;
    _user = null;
    _points = 0;
    _contributions = [];
    _collectionRequests = [];
    _notifications = [];
    _redemptions = [];
    currentContribution = null;
    currentCollectionRequest = null;
    currentFaculty = null;
    currentStation = null;
    currentSession = null;
    final p = await SharedPreferences.getInstance();
    for (final k in [
      _userKey,
      _loggedInKey,
      _pointsKey,
      _contributionsKey,
      _collectionsKey,
      _notificationsKey,
      _redemptionsKey,
    ]) {
      await p.remove(k);
    }
  }

  // ---------------------------------------------------------------------------
  // Recycling flow (maps to future POST /deposit/session etc.)
  // ---------------------------------------------------------------------------

  /// The student tapped "Recycle Now" — the recycling journey begins. A
  /// session is created locally; the station is attached once selected and
  /// the station TABLET scans the student's QR.
  RecyclingSession prepareRecycle() {
    final now = DateTime.now();
    final session = RecyclingSession(
      sessionId: 'sess-${now.millisecondsSinceEpoch}',
      studentId: _user?.studentId ?? '',
      stationId: '',
      startedAt: now,
      expiresAt: now.add(const Duration(minutes: 15)),
      status: SessionStatus.idle,
    );
    currentSession = session;
    return session;
  }

  /// True when the active session has passed its expiry time.
  bool isCurrentSessionExpired() {
    final s = currentSession;
    return s != null && DateTime.now().isAfter(s.expiresAt);
  }

  /// Expires the active session (no points, flow must restart).
  void expireCurrentSession() {
    updateSessionStatus(SessionStatus.expired);
  }

  /// Station chosen at Station Selection. Attaches it to the active session
  /// and moves to [SessionStatus.stationSelected].
  void startRecycle(Station station) {
    currentStation = station;
    currentSession = (currentSession ?? prepareRecycle()).copyWith(
      stationId: station.id,
      status: SessionStatus.stationSelected,
    );
  }

  /// The student's Dynamic QR is now on screen, waiting for the tablet to
  /// scan it (maps conceptually to the tablet's identification step).
  void showQrForDeposit() {
    updateSessionStatus(SessionStatus.waitingForStudentIdentification);
  }

  /// The station tablet scanned the QR and identified the student.
  /// The student may now place waste.
  void confirmStationIdentification() {
    updateSessionStatus(SessionStatus.readyForDeposit);
  }

  void updateSessionStatus(SessionStatus status) {
    final s = currentSession;
    if (s == null) return;
    currentSession = s.copyWith(status: status);
  }

  /// Creates the draft contribution the processing/verification flow uses.
  /// The material, weight and confidence describe what the station hardware
  /// classified — simulated locally until the Rotary Sorting Mechanism V2 is
  /// connected. No points are awarded here — only after
  /// [completeVerifiedDeposit].
  Contribution newDraftContribution() {
    final now = DateTime.now();
    final rng = Random(now.millisecondsSinceEpoch);
    final materials = ['Plastic', 'Metal', 'Paper', 'Other'];
    final materialType = materials[rng.nextInt(materials.length)];
    final weight = 5.0 + rng.nextDouble() * 115.0; // grams
    final confidence = 85.0 + rng.nextDouble() * 14.0; // 85–99 %
    return Contribution(
      id: 'EL-${now.year}-${(100000 + now.microsecondsSinceEpoch % 900000).toString()}',
      materialType: materialType,
      weight: double.parse(weight.toStringAsFixed(1)),
      aiConfidence: double.parse(confidence.toStringAsFixed(1)),
      targetBin: '$materialType Bin',
      points: pointsForMaterial(materialType),
      stationId: currentStation?.id ?? '',
      timestamp: now,
      verificationStatus: 'DROP_CONFIRMED',
    );
  }

  /// A verified recycling transaction awarded points. Called ONLY after the
  /// physical verification chain (AI classify -> bin -> drop -> weight).
  Future<void> completeVerifiedDeposit(Contribution contribution) async {
    updateSessionStatus(SessionStatus.completed);
    _points += contribution.points;
    currentContribution = contribution;
    _contributions.insert(0, contribution);
    _notifications.insert(
      0,
      AppNotification(
        id: 'n-${DateTime.now().millisecondsSinceEpoch}',
        title: 'You earned ${contribution.points} EcoPoints',
        body:
            '${contribution.materialType} verified at ${currentStation?.name ?? 'an Ecolamp station'}.',
        time: 'Just now',
        iconKey: 'eco',
      ),
    );
    await _persistUserData();
  }

  // ---------------------------------------------------------------------------
  // Rewards redemption (local until POST /rewards/redeem exists)
  // ---------------------------------------------------------------------------

  /// Redeems [cost] points for [rewardId]. Deducts and persists atomically;
  /// fails when the balance is insufficient. Never grants negative points.
  Future<RedeemResult> redeemReward({
    required String rewardId,
    required int cost,
  }) async {
    if (_points < cost || cost < 0) return RedeemResult.insufficientPoints;
    _points -= cost;
    _redemptions.insert(0, {
      'rewardId': rewardId,
      'cost': cost,
      'at': DateTime.now().toIso8601String(),
    });
    _notifications.insert(
      0,
      AppNotification(
        id: 'n-${DateTime.now().millisecondsSinceEpoch}',
        title: 'Reward redeemed',
        body: '$rewardId redeemed for $cost EcoPoints.',
        time: 'Just now',
        iconKey: 'trophy',
      ),
    );
    await _persistUserData();
    return RedeemResult.success;
  }

  // ---------------------------------------------------------------------------
  // Bulk campus collection requests (maps to future POST /collection/request)
  // ---------------------------------------------------------------------------

  /// Registers a bulk campus collection request. No Smart Bin EcoPoints are
  /// awarded — bulk collection points are handled by the backend/admin later.
  Future<CollectionRequest> requestCollection({
    required String materialType,
    required String estimatedQuantity,
    required String collectionPoint,
    required String preferredDate,
    required String timeWindow,
  }) async {
    final now = DateTime.now();
    final request = CollectionRequest(
      id: 'COL-${now.year}-${(100000 + now.microsecondsSinceEpoch % 900000).toString()}',
      materialType: materialType,
      estimatedQuantity: estimatedQuantity,
      collectionPoint: collectionPoint,
      preferredDate: preferredDate,
      timeWindow: timeWindow,
      requestedAt: now,
    );
    currentCollectionRequest = request;
    _collectionRequests.insert(0, request);
    _notifications.insert(
      0,
      AppNotification(
        id: 'n-$now',
        title: 'Collection request received',
        body:
            '${request.id} · $materialType · $estimatedQuantity · $collectionPoint.',
        time: 'Just now',
        iconKey: 'calendar',
      ),
    );
    await _persistUserData();
    return request;
  }

  void markNotificationRead(String id) {
    _notifications = _notifications
        .map((n) => n.id == id ? n.markRead() : n)
        .toList();
    _persistUserData();
  }

  Future<void> _persistUserData() async {
    final p = await SharedPreferences.getInstance();
    await p.setInt(_pointsKey, _points);
    await p.setStringList(
      _contributionsKey,
      _contributions.map((e) => jsonEncode(e.toJson())).toList(),
    );
    await p.setStringList(
      _collectionsKey,
      _collectionRequests.map((e) => jsonEncode(e.toJson())).toList(),
    );
    await p.setStringList(
      _notificationsKey,
      _notifications.map((e) => jsonEncode(e.toJson())).toList(),
    );
    await p.setStringList(
      _redemptionsKey,
      _redemptions.map((e) => jsonEncode(e)).toList(),
    );
  }
}
