import 'package:flutter/foundation.dart';

/// Which data path the app runs on.
///
/// - [demo] (default): the fully-local SCWT experience. Auth is a local
///   session, points/history live in `shared_preferences`, deposits run the
///   simulated verification chain. Clearly isolated — never mixed with
///   production data.
/// - [production]: every screen reads authoritative data from the Recycle
///   Vision FastAPI backend. The client NEVER awards points; it mirrors what
///   the backend persisted.
enum AppMode { demo, production }

/// Compile-time + runtime configuration.
///
/// Enable the production backend with `--dart-define`:
/// ```
/// flutter run --dart-define=SCWT_MODE=production \
///   --dart-define=API_BASE_URL=http://10.0.2.2:8100/api/v1
/// ```
/// Non-debug builds REQUIRE an explicit HTTPS API_BASE_URL.
abstract final class AppConfig {
  static const _modeOverride = String.fromEnvironment('SCWT_MODE');
  static const _apiBaseUrlOverride = String.fromEnvironment('API_BASE_URL');

  static AppMode get mode {
    if (_modeOverride.toLowerCase() == 'production') return AppMode.production;
    return AppMode.demo;
  }

  static bool get isProduction => mode == AppMode.production;

  static String get apiBaseUrl {
    if (_apiBaseUrlOverride.isNotEmpty) {
      if (!kDebugMode && !_apiBaseUrlOverride.startsWith('https://')) {
        throw StateError(
          'API_BASE_URL must use HTTPS in non-debug builds. '
          'Provide --dart-define=API_BASE_URL=https://...',
        );
      }
      return _apiBaseUrlOverride;
    }
    assert(
      kDebugMode,
      'API_BASE_URL must be set via --dart-define for non-debug builds. '
      'Example: --dart-define=API_BASE_URL=https://api.yourdomain.com/api/v1',
    );
    if (!kIsWeb &&
        defaultTargetPlatform == TargetPlatform.android &&
        kDebugMode) {
      return 'http://10.0.2.2:8100/api/v1';
    }
    return 'http://localhost:8100/api/v1';
  }
}
