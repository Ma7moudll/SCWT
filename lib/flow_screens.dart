import 'dart:async';

import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';

import 'api/api_client.dart';
import 'api/app_config.dart';
import 'api/backend_gateway.dart';
import 'api/contract.dart';
import 'models.dart';
import 'repositories.dart';
import 'app_flow_nav.dart';
import 'screens.dart';
import 'store.dart';
import 'theme.dart';

// ---------------------------------------------------------------------------
// A. MY ECOLOOP QR
// ---------------------------------------------------------------------------

/// Production-mode deposit handoff state shared between screens.
class DepositHandoff {
  /// Set by MyQr when the backend reports a claimed deposit session (the
  /// station claimed the student's handoff QR). The Processing screen watches
  /// this operation live.
  static String? liveOperationId;
}

class MyQr extends StatefulWidget {
  const MyQr({super.key, required this.go});
  final Go go;
  @override
  State<MyQr> createState() => _MyQrState();
}

class _MyQrState extends State<MyQr> {
  static const _validSeconds = 30;
  Timer? _timer;
  Timer? _pollTimer;
  int _remaining = _validSeconds;
  late String _qrData;
  String? _handoffError;
  String? _handoffToken;

  @override
  void initState() {
    super.initState();
    // Arriving from "Recycle Now" the session is stationSelected: present the
    // Dynamic QR and wait for the station tablet to scan it.
    if (AppStore.instance.currentSession?.status ==
        SessionStatus.stationSelected) {
      AppStore.instance.showQrForDeposit();
    }
    _qrData = _nextQrData();
    if (AppConfig.isProduction) {
      _mintHandoffToken();
      _pollForClaimedOperation();
    }
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      setState(() {
        if (_remaining <= 1) {
          _remaining = _validSeconds;
          if (AppConfig.isProduction) {
            // Re-mint the single-use handoff token.
            _mintHandoffToken();
          } else {
            _qrData = _nextQrData();
          }
        } else {
          _remaining--;
        }
      });
    });
  }

  /// Production: the QR carries a short-lived single-use handoff token; the
  /// station tablet scans it and claims the deposit session server-side.
  Future<void> _mintHandoffToken() async {
    try {
      final t = await BackendGateway.instance.mintHandoffToken();
      if (!mounted) return;
      setState(() {
        _handoffError = null;
        _handoffToken = t.token;
        _qrData = BackendGateway.handoffQrPayload(t.token);
        _remaining = t.expiresAt
            .difference(DateTime.now())
            .inSeconds
            .clamp(5, 120);
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _handoffError = e.message);
    } catch (_) {
      if (mounted) {
        setState(() => _handoffError = 'Cannot reach Ecolamp right now.');
      }
    }
  }

  /// Production: once the station claims the QR a non-terminal deposit
  /// session exists — hand off to the live Processing view.
  void _pollForClaimedOperation() {
    _pollTimer = Timer.periodic(const Duration(seconds: 2), (_) async {
      if (!mounted) {
        _pollTimer?.cancel();
        return;
      }
      try {
        final op = await BackendGateway.instance.activeOperation();
        if (op != null && mounted) {
          _pollTimer?.cancel();
          setState(() => DepositHandoff.liveOperationId = op.operationId);
          widget.go(Screen.processing);
        }
      } catch (_) {
        // transient network error — keep polling
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _pollTimer?.cancel();
    super.dispose();
  }

  String _nextQrData() {
    if (AppConfig.isProduction && _handoffToken != null) {
      return BackendGateway.handoffQrPayload(_handoffToken!);
    }
    return 'ECOLOOP:${AppStore.instance.user?.studentId ?? 'ANONYMOUS'}:${DateTime.now().millisecondsSinceEpoch}';
  }

  String get _countdown =>
      '${(_remaining ~/ 60).toString().padLeft(2, '0')}:${(_remaining % 60).toString().padLeft(2, '0')}';

  void _refresh() {
    setState(() {
      _remaining = _validSeconds;
      _qrData = _nextQrData();
    });
    showToast(context, 'QR refreshed');
  }

  @override
  Widget build(BuildContext context) {
    final session = AppStore.instance.currentSession;
    final inSession =
        session != null &&
        (session.status == SessionStatus.stationSelected ||
            session.status == SessionStatus.waitingForStudentIdentification ||
            session.status == SessionStatus.studentIdentified ||
            session.status == SessionStatus.readyForDeposit);
    final depositReady =
        session != null &&
        (session.status == SessionStatus.studentIdentified ||
            session.status == SessionStatus.readyForDeposit);
    final station = AppStore.instance.currentStation;

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'My Ecolamp QR', back: true, go: widget.go),
          const SizedBox(height: 6),
          if (_handoffError != null) ...[
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              margin: const EdgeInsets.only(bottom: 12),
              decoration: BoxDecoration(
                color: const Color(0xFFfdf2f1),
                border: Border.all(color: const Color(0xFFefd2ce)),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Row(
                children: [
                  const Icon(Icons.wifi_off, size: 15, color: AppColors.red),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '$_handoffError',
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.red,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
          Center(
            child: Column(
              children: [
                Text(
                  inSession
                      ? (depositReady ? 'Ready to Deposit' : 'Ready to Recycle')
                      : 'Scan this code at an Ecolamp station',
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.mutedForeground,
                  ),
                ),
              ],
            ),
          ),
          if (inSession) ...[
            const SizedBox(height: 14),
            Container(
              padding: const EdgeInsets.all(13),
              decoration: BoxDecoration(
                color: const Color(0xFF12a953),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(
                depositReady
                    ? '${station?.name ?? 'Ecolamp Station'}\nPlace your waste to begin recycling.'
                    : '${station?.name ?? 'Ecolamp Station'}\nShow this QR code to the station tablet.',
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.9),
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  height: 1.4,
                ),
              ),
            ),
            const SizedBox(height: 14),
          ] else
            const SizedBox(height: 22),
          Center(
            child: Container(
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(
                color: AppColors.card,
                border: Border.all(color: const Color(0xFFe0eee6)),
                borderRadius: BorderRadius.circular(22),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x141b5b3a),
                    blurRadius: 24,
                    offset: Offset(0, 10),
                  ),
                ],
              ),
              child: QrImageView(
                data: _qrData,
                version: QrVersions.auto,
                size: 190,
                errorCorrectionLevel: QrErrorCorrectLevel.M,
                backgroundColor: Colors.white,
                eyeStyle: const QrEyeStyle(
                  eyeShape: QrEyeShape.square,
                  color: AppColors.darkGreen,
                ),
                dataModuleStyle: const QrDataModuleStyle(
                  dataModuleShape: QrDataModuleShape.square,
                  color: AppColors.foreground,
                ),
              ),
            ),
          ),
          const SizedBox(height: 18),
          Center(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              decoration: BoxDecoration(
                color: AppColors.lightGreenBg,
                borderRadius: BorderRadius.circular(999),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.timer_outlined,
                    size: 15,
                    color: AppColors.successGreen,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    'Valid for $_countdown',
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.successGreen,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),
          const Center(
            child: Text(
              'QR refreshes automatically',
              style: TextStyle(fontSize: 11, color: AppColors.mutedForeground),
            ),
          ),
          if (inSession) ...[
            const SizedBox(height: 14),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(
                  Icons.sensors,
                  size: 14,
                  color: AppColors.successGreen,
                ),
                const SizedBox(width: 6),
                Flexible(
                  child: Text(
                    depositReady
                        ? 'Station identified — you may deposit.'
                        : 'Waiting for station…',
                    textAlign: TextAlign.center,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.darkGreen,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
          ],
          const SizedBox(height: 22),
          PrimaryButton(
            label: depositReady
                ? 'Start Recycling'
                : inSession
                ? 'Station scanned my QR'
                : 'Refresh QR',
            icon: depositReady
                ? Icons.recycling
                : inSession
                ? Icons.sensors
                : Icons.refresh,
            onTap: depositReady
                ? () => widget.go(Screen.processing)
                : inSession
                ? () => setState(
                    () => AppStore.instance.confirmStationIdentification(),
                  )
                : _refresh,
          ),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: const Color(0xFFf1faf5),
              border: Border.all(color: const Color(0xFFdcefe4)),
              borderRadius: BorderRadius.circular(13),
            ),
            child: Row(
              children: [
                Container(
                  width: 30,
                  height: 30,
                  decoration: BoxDecoration(
                    color: AppColors.primary,
                    borderRadius: BorderRadius.circular(9),
                  ),
                  child: const Icon(
                    Icons.sensors,
                    size: 17,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        inSession ? 'Recycling Session' : 'Session ready',
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        station?.name ?? 'No station selected',
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.successGreen,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// B. COLLECTION REQUEST CREATED
// ---------------------------------------------------------------------------

class CollectionCreated extends StatelessWidget {
  const CollectionCreated({super.key, required this.go});
  final Go go;
  @override
  Widget build(BuildContext context) {
    final req =
        AppStore.instance.currentCollectionRequest ??
        (AppStore.instance.collectionRequests.isEmpty
            ? null
            : AppStore.instance.collectionRequests.first);
    if (req == null) {
      return Scaffold(
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                ScreenHeader(title: 'Collection Request', back: true, go: go),
                const SizedBox(height: 40),
                const Text(
                  'No collection request found',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AppColors.mutedForeground,
                    fontSize: 13,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'Collection Request Created', back: true, go: go),
          const SizedBox(height: 5),
          Center(
            child: Container(
              width: 112,
              height: 112,
              decoration: BoxDecoration(
                border: Border.all(color: const Color(0xFFbde6ce), width: 2),
                borderRadius: BorderRadius.circular(22),
              ),
              child: const Icon(
                Icons.check_rounded,
                size: 55,
                color: AppColors.darkGreen,
              ),
            ),
          ),
          const SizedBox(height: 20),
          const Text(
            'Request received.\nOur campus team will review it shortly.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 13, height: 1.5),
          ),
          const SizedBox(height: 22),
          Container(
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0xFFe0eee6)),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              children: [
                _RequestRow('Request ID', req.id),
                _RequestRow('Material', req.materialType),
                _RequestRow('Estimated Weight', req.estimatedQuantity),
                _RequestRow('Collection Point', req.collectionPoint),
                _RequestRow('Preferred Date', req.preferredDate),
                _RequestRow('Time Window', req.timeWindow),
                _RequestRow('Status', req.statusLabel),
              ],
            ),
          ),
          const SizedBox(height: 24),
          PrimaryButton(
            label: 'Back to Home',
            icon: Icons.home_outlined,
            onTap: () => go(Screen.home),
          ),
        ],
      ),
    );
  }
}

class _RequestRow extends StatelessWidget {
  const _RequestRow(this.label, this.value);
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) {
    final isStatus = label == 'Status';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 12),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFFedf4ef))),
      ),
      child: Row(
        children: [
          Flexible(
            child: Text(
              label,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 11,
                color: AppColors.mutedForeground,
              ),
            ),
          ),
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.end,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w800,
                color: isStatus ? AppColors.statusYellow : AppColors.foreground,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// C. STATION SELECTION
// ---------------------------------------------------------------------------

class StationSelect extends StatefulWidget {
  const StationSelect({super.key, required this.go});
  final Go go;
  @override
  State<StationSelect> createState() => _StationSelectState();
}

class _StationSelectState extends State<StationSelect> {
  late List<Station> stations = AppRepositories.instance.stationsSync();
  Station? _selected;

  @override
  void initState() {
    super.initState();
    if (AppConfig.isProduction) {
      // Production: live station registry from the backend (availability,
      // readiness). Falls back to the last-known list when unreachable.
      BackendGateway.instance
          .fetchStations()
          .then((list) {
            if (mounted && list.isNotEmpty) setState(() => stations = list);
          })
          .catchError((_) {});
    }
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'Select Station', back: true, go: widget.go),
          const SizedBox(height: 4),
          const SectionHeading('Nearby Ecolamp Stations'),
          Column(
            children: stations.map((station) {
              final selected = _selected?.id == station.id;
              final online = station.status == StationStatus.online;
              return Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: InkWell(
                  onTap: online
                      ? () => setState(() => _selected = station)
                      : null,
                  borderRadius: BorderRadius.circular(13),
                  child: Container(
                    padding: const EdgeInsets.all(13),
                    decoration: BoxDecoration(
                      color: !online
                          ? const Color(0xFFf7faf8)
                          : selected
                          ? const Color(0xFFf1faf5)
                          : AppColors.card,
                      border: Border.all(
                        color: selected
                            ? AppColors.primary
                            : const Color(0xFFe0eee6),
                        width: selected ? 1.5 : 1,
                      ),
                      borderRadius: BorderRadius.circular(13),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 10,
                          height: 10,
                          decoration: BoxDecoration(
                            color: online
                                ? (station.availability == 'Almost Full'
                                      ? AppColors.statusYellow
                                      : AppColors.primary)
                                : const Color(0xFFc3ccc7),
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                station.name,
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  color: online
                                      ? AppColors.foreground
                                      : AppColors.mutedForeground,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                online
                                    ? station.availability
                                    : 'Offline — unavailable',
                                style: TextStyle(
                                  fontSize: 11,
                                  color: online
                                      ? AppColors.successGreen
                                      : AppColors.mutedForeground,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ),
                        ),
                        Icon(
                          Icons.chevron_right,
                          size: 15,
                          color: online
                              ? const Color(0xFFa4b3ac)
                              : const Color(0xFFd1dcd5),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            }).toList(),
          ),
          const SizedBox(height: 12),
          PrimaryButton(
            label: _selected == null
                ? 'Choose a station to start'
                : 'Show My QR at Station',
            icon: _selected == null ? Icons.recycling : Icons.qr_code,
            onTap: () {
              final station = _selected;
              if (station == null || station.status == StationStatus.offline) {
                return;
              }
              if (AppStore.instance.isCurrentSessionExpired()) {
                AppStore.instance.expireCurrentSession();
                widget.go(Screen.failed);
                return;
              }
              AppStore.instance.startRecycle(station);
              widget.go(Screen.myQr);
            },
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// C. RECYCLING PROCESSING
// ---------------------------------------------------------------------------

class Processing extends StatefulWidget {
  const Processing({super.key, required this.go});
  final Go go;
  @override
  State<Processing> createState() => _ProcessingState();
}

enum _ProcStatus { done, active, waiting }

class _ProcStep {
  const _ProcStep(this.label, this.subtitle, this.icon);
  final String label;
  final String subtitle;
  final IconData icon;
}

class _ProcessingState extends State<Processing> {
  // One draft drives BOTH the step labels and the awarded contribution so
  // what the user sees classified is exactly what they are credited for.
  late final Contribution _draft = AppStore.instance.newDraftContribution();
  late final List<_ProcStep> steps = _buildSteps(_draft);
  int _stage = 0; // number of completed steps
  Timer? _timer;

  // The 5-stage verification chain. The draft simulates what the station
  // hardware classified; a real backend/device will drive these stages via
  // events when the Rotary Sorting Mechanism V2 is connected.
  List<_ProcStep> _buildSteps(Contribution c) {
    final mat = c.materialType.toUpperCase();
    return [
      _ProcStep(
        'Identifying',
        'Camera · Object detected',
        Icons.photo_camera_outlined,
      ),
      _ProcStep(
        'Classifying',
        'AI Classification · ${c.aiConfidence.toStringAsFixed(0)}%',
        Icons.auto_awesome,
      ),
      _ProcStep('Sorting', 'Routing to $mat bin', Icons.recycling),
      _ProcStep(
        'Verifying',
        'Weight verification',
        Icons.monitor_weight_outlined,
      ),
      _ProcStep(
        'Completed',
        'Drop confirmed · Weight verified',
        Icons.check_circle_outline,
      ),
    ];
  }

  @override
  void initState() {
    super.initState();
    final store = AppStore.instance;
    if (store.isBackendMode) {
      _runBackendFlow(store);
      return;
    }
    if (store.currentSession == null || store.isCurrentSessionExpired()) {
      // No valid recycling session — nothing can be verified.
      store.expireCurrentSession();
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) widget.go(Screen.failed);
      });
      return;
    }
    store.updateSessionStatus(SessionStatus.processing);
    _timer = Timer.periodic(const Duration(milliseconds: 800), (_) async {
      if (!mounted) {
        _timer?.cancel();
        return;
      }
      setState(() {
        if (_stage < steps.length) _stage++;
      });
      if (_stage == 4) {
        AppStore.instance.updateSessionStatus(SessionStatus.verifying);
      }
      if (_stage >= steps.length) {
        _timer?.cancel();
        await _finish();
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  // Points are granted ONLY after the full verification chain completes,
  // and exactly once per deposit (the single _draft).
  Future<void> _finish() async {
    await AppStore.instance.completeVerifiedDeposit(_draft);
    if (mounted) widget.go(Screen.success);
  }

  /// PRODUCTION path: the deposit was claimed by the station; the backend is
  /// the only authority. Live phases drive the same five verification stages,
  /// and the terminal result arrives exclusively from the backend — points
  /// are never computed here.
  Future<void> _runBackendFlow(AppStore store) async {
    final operationId = DepositHandoff.liveOperationId;
    if (operationId == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) widget.go(Screen.failed);
      });
      return;
    }
    store.updateSessionStatus(SessionStatus.processing);
    try {
      final result = await BackendGateway.instance.watchOperation(
        operationId,
        onLive: (live) {
          if (!mounted) return;
          setState(() => _stage = live.status.processingStage);
        },
      );
      if (!mounted) return;
      if (result.status == WireDepositStatus.confirmed) {
        await AppStore.instance.applyAuthoritativeDeposit(
          result.toContribution(),
          stationName: AppStore.instance.currentStation?.name,
        );
        try {
          // Reconcile with backend truth (points balance + history).
          await BackendGateway.instance.syncFromBackend();
        } catch (_) {
          // Offline right now — the authoritative contribution is already
          // shown; the next sync reconciles the balance.
        }
        widget.go(Screen.success);
      } else {
        store.expireCurrentSession();
        widget.go(Screen.failed);
      }
    } on ApiException catch (_) {
      if (mounted) {
        store.expireCurrentSession();
        widget.go(Screen.failed);
      }
    } catch (_) {
      if (mounted) {
        store.expireCurrentSession();
        widget.go(Screen.failed);
      }
    }
  }

  _ProcStatus statusFor(int index) {
    if (index < _stage) return _ProcStatus.done;
    if (index == _stage) return _ProcStatus.active;
    return _ProcStatus.waiting;
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'Recycling', go: widget.go),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.all(13),
            decoration: BoxDecoration(
              color: const Color(0xFF12a953),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(
              AppStore.instance.currentStation?.name ?? 'Ecolamp Station',
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.9),
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          const SizedBox(height: 22),
          Row(
            children: [
              const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(
                  strokeWidth: 2.2,
                  color: AppColors.primary,
                ),
              ),
              const SizedBox(width: 10),
              const Text(
                'Analyzing waste…',
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
              ),
            ],
          ),
          const SizedBox(height: 20),
          Column(
            children: List.generate(steps.length, (i) {
              final status = statusFor(i);
              final step = steps[i];
              return Container(
                margin: const EdgeInsets.only(bottom: 10),
                padding: const EdgeInsets.all(13),
                decoration: BoxDecoration(
                  color: status == _ProcStatus.waiting
                      ? const Color(0xFFf7faf8)
                      : AppColors.card,
                  border: Border.all(color: const Color(0xFFe0eee6)),
                  borderRadius: BorderRadius.circular(13),
                ),
                child: Row(
                  children: [
                    _statusIcon(status),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            step.label,
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              color: status == _ProcStatus.waiting
                                  ? AppColors.mutedForeground
                                  : AppColors.foreground,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            status == _ProcStatus.done
                                ? step.subtitle.replaceAll(
                                    'In progress…',
                                    'Complete',
                                  )
                                : step.subtitle,
                            style: TextStyle(
                              fontSize: 10,
                              color: status == _ProcStatus.done
                                  ? AppColors.successGreen
                                  : AppColors.mutedForeground,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              );
            }),
          ),
        ],
      ),
    );
  }

  Widget _statusIcon(_ProcStatus status) {
    switch (status) {
      case _ProcStatus.done:
        return Container(
          width: 24,
          height: 24,
          decoration: const BoxDecoration(
            color: AppColors.primary,
            shape: BoxShape.circle,
          ),
          child: const Icon(Icons.check, size: 14, color: Colors.white),
        );
      case _ProcStatus.active:
        return const SizedBox(
          width: 24,
          height: 24,
          child: CircularProgressIndicator(
            strokeWidth: 2.2,
            color: AppColors.primary,
          ),
        );
      case _ProcStatus.waiting:
        return Container(
          width: 24,
          height: 24,
          decoration: BoxDecoration(
            border: Border.all(color: const Color(0xFFd1dcd5)),
            shape: BoxShape.circle,
          ),
          child: const Icon(Icons.schedule, size: 14, color: Color(0xFFa6b2ad)),
        );
    }
  }
}

// ---------------------------------------------------------------------------
// D/E. RECYCLING SUCCESS / FAILED
// ---------------------------------------------------------------------------

class RecyclingResult extends StatelessWidget {
  const RecyclingResult({super.key, required this.success, required this.go});
  final bool success;
  final Go go;
  @override
  Widget build(BuildContext context) {
    return success ? const _SuccessBody() : _FailedBody(go: go);
  }
}

class _SuccessBody extends StatefulWidget {
  const _SuccessBody();
  @override
  State<_SuccessBody> createState() => _SuccessBodyState();
}

class _SuccessBodyState extends State<_SuccessBody> {
  Contribution? get c => AppStore.instance.currentContribution;

  @override
  Widget build(BuildContext context) {
    final contribution = c;
    final points = contribution?.points ?? 0;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 28, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Center(
            child: Container(
              width: 76,
              height: 76,
              decoration: const BoxDecoration(
                color: AppColors.primary,
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.check, size: 42, color: Colors.white),
            ),
          ),
          const SizedBox(height: 18),
          const Text(
            'Recycling Complete',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.5,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'Item Accepted',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 13,
              color: AppColors.successGreen,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 22),
          TweenAnimationBuilder<double>(
            tween: Tween(begin: 0, end: 1),
            duration: const Duration(milliseconds: 500),
            curve: Curves.easeOut,
            builder: (context, t, child) => Opacity(
              opacity: t,
              child: Transform.scale(scale: 0.92 + 0.08 * t, child: child),
            ),
            child: Container(
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [Color(0xFFf0faf4), Color(0xFFe4f5ec)],
                ),
                border: Border.all(color: const Color(0xFFd7ece0)),
                borderRadius: BorderRadius.circular(15),
              ),
              child: Column(
                children: [
                  Text(
                    contribution?.materialType ?? 'Plastic',
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    contribution?.weightDisplay ?? '18.4 g',
                    style: const TextStyle(
                      fontSize: 34,
                      fontWeight: FontWeight.w700,
                      letterSpacing: -1,
                    ),
                  ),
                  const SizedBox(height: 10),
                  TweenAnimationBuilder<int>(
                    tween: IntTween(begin: 0, end: points),
                    duration: const Duration(milliseconds: 700),
                    builder: (context, v, child) => Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: AppColors.primary,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        '+$v EcoPoints',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 13,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 18),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: const Color(0xFFf1faf5),
              border: Border.all(color: const Color(0xFFdcefe4)),
              borderRadius: BorderRadius.circular(13),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: const [
                Text(
                  'Verification',
                  style: TextStyle(
                    fontSize: 10,
                    color: AppColors.mutedForeground,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                SizedBox(height: 10),
                _VerifiedCheck(label: 'AI Classified'),
                SizedBox(height: 8),
                _VerifiedCheck(label: 'Correct Bin'),
                SizedBox(height: 8),
                _VerifiedCheck(label: 'Drop Confirmed'),
                SizedBox(height: 8),
                _VerifiedCheck(label: 'Weight Verified'),
              ],
            ),
          ),
          const SizedBox(height: 18),
          Text(
            AppStore.instance.currentStation?.name ?? 'Ecolamp Station',
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 12,
              color: AppColors.mutedForeground,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Transaction ID: ${contribution?.id ?? 'EL-2026-000124'}',
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 11,
              color: AppColors.mutedForeground,
              letterSpacing: 0.3,
            ),
          ),
          const SizedBox(height: 28),
          PrimaryButton(
            label: 'View Contribution',
            icon: Icons.receipt_long,
            onTap: () => goDetail(context),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              onPressed: () => goHome(context),
              style: OutlinedButton.styleFrom(
                foregroundColor: AppColors.darkGreen,
                side: const BorderSide(color: Color(0xFFdcece3)),
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              child: const Text(
                'Done',
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800),
              ),
            ),
          ),
        ],
      ),
    );
  }

  void goDetail(BuildContext context) {
    AppFlowNav.of(context)?.call(Screen.contributionDetail);
  }

  void goHome(BuildContext context) {
    AppFlowNav.of(context)?.call(Screen.home);
  }
}

class _VerifiedCheck extends StatelessWidget {
  const _VerifiedCheck({required this.label});
  final String label;
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const Icon(Icons.check_circle, size: 14, color: AppColors.successGreen),
        const SizedBox(width: 8),
        Text(
          label,
          style: const TextStyle(
            fontSize: 11,
            color: AppColors.foreground,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _FailedBody extends StatelessWidget {
  const _FailedBody({required this.go});
  final Go go;
  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 32, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Center(
            child: Container(
              width: 76,
              height: 76,
              decoration: const BoxDecoration(
                color: Color(0x22f04f45),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.error_outline,
                size: 42,
                color: AppColors.red,
              ),
            ),
          ),
          const SizedBox(height: 18),
          const Text(
            'Something went wrong',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 6),
          const Text(
            'The waste drop could not be verified.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 13, color: AppColors.mutedForeground),
          ),
          const SizedBox(height: 22),
          Container(
            padding: const EdgeInsets.all(13),
            decoration: BoxDecoration(
              color: const Color(0xFFfdf2f1),
              border: Border.all(color: const Color(0xFFefd2ce)),
              borderRadius: BorderRadius.circular(13),
            ),
            child: Row(
              children: [
                const Icon(
                  Icons.verified_user_outlined,
                  size: 18,
                  color: AppColors.red,
                ),
                const SizedBox(width: 10),
                Text(
                  'Drop verification failed',
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.red,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 28),
          PrimaryButton(
            label: 'Try Again',
            icon: Icons.refresh,
            onTap: () => go(Screen.station),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              onPressed: () => go(Screen.home),
              style: OutlinedButton.styleFrom(
                foregroundColor: AppColors.darkGreen,
                side: const BorderSide(color: Color(0xFFdcece3)),
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              child: const Text(
                'Cancel',
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// F. CONTRIBUTION DETAILS
// ---------------------------------------------------------------------------

class ContributionDetail extends StatelessWidget {
  const ContributionDetail({super.key, required this.go});
  final Go go;
  @override
  Widget build(BuildContext context) {
    final c = AppStore.instance.currentContribution;
    if (c == null) {
      return _buildEmpty(go);
    }
    return _buildDetail(go, c);
  }

  Widget _buildEmpty(Go go) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ScreenHeader(title: 'Contribution', back: true, go: go),
              const SizedBox(height: 40),
              const Text(
                'No contribution selected',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: AppColors.mutedForeground,
                  fontSize: 13,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDetail(Go go, Contribution c) {
    final rows = <(String, Widget)>[
      ('Material', Text(c.materialType, style: _rowValue)),
      ('Weight', Text(c.weightDisplay, style: _rowValue)),
      (
        'AI Confidence',
        Text('${c.aiConfidence.toStringAsFixed(0)}%', style: _rowValue),
      ),
      ('Destination', Text(c.targetBin, style: _rowValue)),
      (
        'Points',
        Text(
          '+${c.points}',
          style: _rowValue.copyWith(
            color: AppColors.successGreen,
            fontWeight: FontWeight.w800,
          ),
        ),
      ),
      ('Date', Text(c.dateDisplay, style: _rowValue)),
      ('Time', Text(c.timeDisplay, style: _rowValue)),
      ('Station', Text(_stationName(c.stationId), style: _rowValue)),
      (
        'Verification',
        Text(
          c.verificationStatus.toUpperCase(),
          style: _rowValue.copyWith(
            color: AppColors.successGreen,
            fontWeight: FontWeight.w800,
          ),
        ),
      ),
      (
        'Transaction ID',
        Text(c.id, style: _rowValue.copyWith(fontSize: 11, letterSpacing: 0.3)),
      ),
    ];
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'Contribution', back: true, go: go),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [Color(0xFFf0faf4), Color(0xFFe4f5ec)],
              ),
              border: Border.all(color: const Color(0xFFd7ece0)),
              borderRadius: BorderRadius.circular(15),
            ),
            child: Row(
              children: [
                Container(
                  width: 46,
                  height: 46,
                  decoration: const BoxDecoration(
                    color: AppColors.primary,
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(Icons.check, size: 26, color: Colors.white),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${c.materialType} recycling',
                        style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '${c.weightDisplay} · ${c.timeDisplay}',
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.mutedForeground,
                        ),
                      ),
                    ],
                  ),
                ),
                Text(
                  '+${c.points} pts',
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.successGreen,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 17),
          Container(
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0xFFe0eee6)),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              children: rows.map((r) {
                return Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 13,
                    vertical: 13,
                  ),
                  decoration: const BoxDecoration(
                    border: Border(
                      bottom: BorderSide(color: Color(0xFFedf4ef)),
                    ),
                  ),
                  child: Row(
                    children: [
                      Text(
                        r.$1,
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.mutedForeground,
                        ),
                      ),
                      const Spacer(),
                      r.$2,
                    ],
                  ),
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 18),
          PrimaryButton(label: 'Done', onTap: () => go(Screen.home)),
        ],
      ),
    );
  }

  static const _rowValue = TextStyle(
    fontSize: 11.5,
    color: AppColors.foreground,
    fontWeight: FontWeight.w700,
  );

  String _stationName(String id) {
    if (id.isEmpty) return 'Ecolamp Station';
    final match = AppRepositories.instance.stationsSync().where(
      (s) => s.id == id,
    );
    return match.isEmpty ? 'Ecolamp Station' : match.first.name;
  }
}

// ---------------------------------------------------------------------------
// G. FACULTY LEADERBOARD
// ---------------------------------------------------------------------------

class Leaderboard extends StatefulWidget {
  const Leaderboard({super.key, required this.go});
  final Go go;
  @override
  State<Leaderboard> createState() => _LeaderboardState();
}

class _LeaderboardState extends State<Leaderboard> {
  static const _periods = ['Weekly', 'Monthly', 'All Time'];
  String _period = 'Weekly';

  @override
  Widget build(BuildContext context) {
    final entries = AppRepositories.instance.leaderboardSync(_period);
    final myEntry = entries.first;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'Ecolamp Faculty Cup', back: true, go: widget.go),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: const Color(0xFFf1faf5),
              border: Border.all(color: const Color(0xFFdcefe4)),
              borderRadius: BorderRadius.circular(13),
            ),
            child: Row(
              children: [
                Container(
                  width: 38,
                  height: 38,
                  decoration: BoxDecoration(
                    color: AppColors.primary,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: const Icon(
                    Icons.school,
                    size: 19,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Your Faculty',
                        style: TextStyle(
                          fontSize: 10,
                          color: AppColors.mutedForeground,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '#${myEntry.rank} · ${myEntry.facultyName}',
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.darkGreen,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${_formatNum(myEntry.points)} points',
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.successGreen,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  AppColors.splashTop.withValues(alpha: 0.95),
                  AppColors.darkGreen,
                ],
              ),
              borderRadius: BorderRadius.circular(15),
            ),
            child: Row(
              children: [
                Container(
                  width: 48,
                  height: 48,
                  decoration: const BoxDecoration(
                    color: Color(0xFF1cc766),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    Icons.emoji_events,
                    color: Colors.white,
                    size: 26,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${myEntry.facultyName} Faculty',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 13,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Rank #${myEntry.rank} · you have ${_formatNum(AppStore.instance.points)} pts',
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.85),
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          Row(
            children: _periods.map((p) {
              final active = _period == p;
              return Padding(
                padding: const EdgeInsets.only(right: 7),
                child: ChoiceChip(
                  label: Text(p, style: const TextStyle(fontSize: 11)),
                  selected: active,
                  onSelected: (_) => setState(() => _period = p),
                  selectedColor: AppColors.darkGreen,
                  labelStyle: TextStyle(
                    color: active ? Colors.white : AppColors.mutedForeground,
                    fontWeight: FontWeight.w600,
                    fontSize: 11,
                  ),
                  backgroundColor: Colors.white,
                  side: BorderSide(
                    color: active ? AppColors.darkGreen : AppColors.border,
                  ),
                  showCheckmark: false,
                  padding: EdgeInsets.zero,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
              );
            }).toList(),
          ),
          const SizedBox(height: 16),
          const SectionHeading('Top Faculties'),
          Container(
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0xFFe0eee6)),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              children: entries.map((e) {
                final isYou = e.facultyName == 'Engineering';
                return InkWell(
                  onTap: () {
                    AppStore.instance.currentFaculty = AppRepositories.instance
                        .facultiesSync()
                        .firstWhere((f) => f.id == e.facultyId);
                    widget.go(Screen.facultyDetail);
                  },
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 13,
                      vertical: 13,
                    ),
                    decoration: BoxDecoration(
                      color: isYou
                          ? const Color(0xFFf1faf5)
                          : Colors.transparent,
                      border: const Border(
                        bottom: BorderSide(color: Color(0xFFedf4ef)),
                      ),
                    ),
                    child: Row(
                      children: [
                        SizedBox(
                          width: 26,
                          child: Text(
                            '${e.rank}',
                            style: TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w800,
                              color: isYou
                                  ? AppColors.primary
                                  : AppColors.mutedForeground,
                            ),
                          ),
                        ),
                        if (_medalFor(e.rank) != null)
                          Icon(
                            _medalFor(e.rank),
                            size: 18,
                            color: _medalColor(e.rank),
                          )
                        else
                          const SizedBox(width: 18),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Flexible(
                                    child: Text(
                                      e.facultyName,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                        fontSize: 12,
                                        fontWeight: FontWeight.w700,
                                        color: AppColors.foreground,
                                      ),
                                    ),
                                  ),
                                  if (isYou) ...[
                                    const SizedBox(width: 6),
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 6,
                                        vertical: 2,
                                      ),
                                      decoration: BoxDecoration(
                                        color: AppColors.primary,
                                        borderRadius: BorderRadius.circular(
                                          999,
                                        ),
                                      ),
                                      child: const Text(
                                        'You',
                                        style: TextStyle(
                                          fontSize: 9,
                                          color: Colors.white,
                                          fontWeight: FontWeight.w700,
                                        ),
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(
                                '${_formatNum(e.points)} points · ${_formatWeight(e.weightKg)} recovered',
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: AppColors.mutedForeground,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
        ],
      ),
    );
  }

  IconData? _medalFor(int rank) => switch (rank) {
    1 => Icons.emoji_events,
    2 => Icons.workspace_premium,
    3 => Icons.military_tech,
    _ => null,
  };

  Color _medalColor(int rank) => switch (rank) {
    1 => const Color(0xFFffb126),
    2 => const Color(0xFF9aa6a0),
    3 => const Color(0xFFc98a4b),
    _ => AppColors.mutedForeground,
  };

  String _formatNum(int n) => n.toString().replaceAllMapped(
    RegExp(r'(\d)(?=(\d{3})+$)'),
    (m) => '${m[1]},',
  );

  String _formatWeight(double kg) => '${kg.toStringAsFixed(0)} kg';
}

// ---------------------------------------------------------------------------
// H. FACULTY DETAILS
// ---------------------------------------------------------------------------

class FacultyDetail extends StatelessWidget {
  const FacultyDetail({super.key, required this.go});
  final Go go;
  @override
  Widget build(BuildContext context) {
    final f = AppStore.instance.currentFaculty;
    if (f == null) return _empty(go);
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'Faculty', back: true, go: go),
          const SizedBox(height: 4),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  AppColors.splashTop.withValues(alpha: 0.95),
                  AppColors.darkGreen,
                ],
              ),
              borderRadius: BorderRadius.circular(15),
            ),
            child: Row(
              children: [
                Container(
                  width: 48,
                  height: 48,
                  decoration: const BoxDecoration(
                    color: Color(0xFF1cc766),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    Icons.school,
                    color: Colors.white,
                    size: 24,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${f.name} Faculty',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 14,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Rank #${f.rank} in the Faculty Cup',
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.85),
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 17),
          Container(
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0xFFe0eee6)),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              children: [
                _statRow(
                  'Total EcoPoints',
                  _formatNum(f.points),
                  Icons.emoji_events,
                  AppColors.statusYellow,
                ),
                _statRow(
                  'Recovered Material',
                  '${f.weightKg.toStringAsFixed(0)} kg',
                  Icons.recycling,
                  AppColors.green,
                ),
                _statRow(
                  'Participating Students',
                  _formatNum(f.students),
                  Icons.groups,
                  AppColors.blue,
                ),
              ],
            ),
          ),
          const SizedBox(height: 17),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [Color(0xFFf3faf6), Color(0xFFe4f4ea)],
              ),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Progress this week',
                  style: TextStyle(
                    fontSize: 10,
                    color: AppColors.mutedForeground,
                  ),
                ),
                const SizedBox(height: 9),
                Container(
                  height: 6,
                  decoration: BoxDecoration(
                    color: const Color(0xFFcce7d6),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: FractionallySizedBox(
                    alignment: Alignment.centerLeft,
                    widthFactor: f.weeklyProgress,
                    child: Container(
                      decoration: BoxDecoration(
                        color: AppColors.primary,
                        borderRadius: BorderRadius.circular(999),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  '${(f.weeklyProgress * 100).toStringAsFixed(0)}% towards the weekly goal',
                  style: const TextStyle(
                    fontSize: 10,
                    color: AppColors.successGreen,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          const SectionHeading('Recent Contributions'),
          if (f.recentContributions.isEmpty)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFFf7faf8),
                borderRadius: BorderRadius.circular(13),
              ),
              child: const Text(
                'No recent contributions yet.',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 11,
                  color: AppColors.mutedForeground,
                ),
              ),
            )
          else
            Column(
              children: f.recentContributions.map((c) {
                return InkWell(
                  onTap: () {
                    AppStore.instance.currentContribution = c;
                    go(Screen.contributionDetail);
                  },
                  borderRadius: BorderRadius.circular(13),
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 10),
                    padding: const EdgeInsets.all(13),
                    decoration: BoxDecoration(
                      border: Border.all(color: const Color(0xFFe0eee6)),
                      borderRadius: BorderRadius.circular(13),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 35,
                          height: 35,
                          decoration: BoxDecoration(
                            color: const Color(0xFFeaf8ef),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: const Icon(
                            Icons.recycling,
                            size: 18,
                            color: AppColors.successGreen,
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '${c.materialType} recycling',
                                style: const TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                '${c.dateDisplay} · ${c.weightDisplay}',
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: AppColors.mutedForeground,
                                ),
                              ),
                            ],
                          ),
                        ),
                        Text(
                          '+${c.points} pts',
                          style: const TextStyle(
                            fontSize: 11,
                            color: AppColors.successGreen,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                  ),
                );
              }).toList(),
            ),
        ],
      ),
    );
  }

  Widget _statRow(String label, String value, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 12),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFFedf4ef))),
      ),
      child: Row(
        children: [
          Container(
            width: 25,
            height: 25,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
            child: Icon(icon, size: 14, color: Colors.white),
          ),
          const SizedBox(width: 10),
          Text(
            label,
            style: const TextStyle(fontSize: 11, color: AppColors.foreground),
          ),
          const Spacer(),
          Text(
            value,
            style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800),
          ),
        ],
      ),
    );
  }

  Widget _empty(Go go) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ScreenHeader(title: 'Faculty', back: true, go: go),
              const SizedBox(height: 40),
              const Text(
                'No faculty selected',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: AppColors.mutedForeground,
                  fontSize: 13,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _formatNum(int n) => n.toString().replaceAllMapped(
    RegExp(r'(\d)(?=(\d{3})+$)'),
    (m) => '${m[1]},',
  );
}

// ---------------------------------------------------------------------------
// I. NOTIFICATIONS
// ---------------------------------------------------------------------------

class Notifications extends StatelessWidget {
  const Notifications({super.key, required this.go});
  final Go go;
  @override
  Widget build(BuildContext context) {
    final items = AppStore.instance.notifications;
    if (items.isEmpty) {
      return Scaffold(
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                ScreenHeader(title: 'Notifications', back: true, go: go),
                const SizedBox(height: 40),
                const Text(
                  'You have no notifications',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AppColors.mutedForeground,
                    fontSize: 13,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'Notifications', back: true, go: go),
          const SizedBox(height: 12),
          Column(
            children: items.map((n) {
              return InkWell(
                onTap: () {
                  if (!n.read) {
                    AppStore.instance.markNotificationRead(n.id);
                    setUnreadRefresh(context);
                  }
                },
                borderRadius: BorderRadius.circular(13),
                child: Container(
                  margin: const EdgeInsets.only(bottom: 10),
                  padding: const EdgeInsets.all(13),
                  decoration: BoxDecoration(
                    color: n.read ? AppColors.card : const Color(0xFFf1faf5),
                    border: Border.all(
                      color: n.read
                          ? const Color(0xFFe0eee6)
                          : AppColors.primary,
                    ),
                    borderRadius: BorderRadius.circular(13),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        width: 38,
                        height: 38,
                        decoration: BoxDecoration(
                          color: _iconBg(n.iconKey),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Icon(
                          _iconFor(n.iconKey),
                          size: 19,
                          color: _iconColor(n.iconKey),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Expanded(
                                  child: Text(
                                    n.title,
                                    style: TextStyle(
                                      fontSize: 12,
                                      fontWeight: n.read
                                          ? FontWeight.w600
                                          : FontWeight.w800,
                                      color: n.read
                                          ? AppColors.foreground
                                          : AppColors.darkGreen,
                                    ),
                                  ),
                                ),
                                if (!n.read)
                                  Container(
                                    width: 8,
                                    height: 8,
                                    margin: const EdgeInsets.only(
                                      top: 4,
                                      left: 6,
                                    ),
                                    decoration: const BoxDecoration(
                                      color: AppColors.notice,
                                      shape: BoxShape.circle,
                                    ),
                                  ),
                              ],
                            ),
                            const SizedBox(height: 4),
                            Text(
                              n.body,
                              style: const TextStyle(
                                fontSize: 11,
                                color: AppColors.mutedForeground,
                                height: 1.4,
                              ),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              n.time,
                              style: const TextStyle(
                                fontSize: 10,
                                color: Color(0xFFa4b3ac),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  void setUnreadRefresh(BuildContext context) {
    // force the StatelessWidget to rebuild against the updated store
    (context as Element).markNeedsBuild();
  }

  IconData _iconFor(String key) => switch (key) {
    'trophy' => Icons.emoji_events,
    'badge' => Icons.workspace_premium,
    'calendar' => Icons.calendar_today,
    'chart' => Icons.bar_chart,
    'station' => Icons.sensors,
    _ => Icons.eco,
  };

  Color _iconBg(String key) => key == 'station'
      ? const Color(0xFFedf5ff)
      : key == 'calendar'
      ? const Color(0xFFFFf6e6)
      : const Color(0xFFeef9f2);

  Color _iconColor(String key) => key == 'station'
      ? AppColors.stepBlue
      : key == 'calendar'
      ? AppColors.statusYellow
      : AppColors.primary;
}
