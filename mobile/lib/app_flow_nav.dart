import 'package:flutter/material.dart' show BuildContext, VoidCallback;

/// App-level flow controller. Registered once by the app shell in main.dart so
/// any screen can navigate between [Screen]s and logout can reset the
/// authenticated flow.
class AppFlowNav {
  AppFlowNav._();
  static Go? _go;
  static VoidCallback? _onLogout;

  static void provide(Go go, {VoidCallback? onLogout}) {
    _go = go;
    _onLogout = onLogout;
  }

  static Go? of(BuildContext context) => _go;

  /// Resets the app back to the Login screen (called after store.logout()).
  static VoidCallback? logoutAction(BuildContext context) => _onLogout;
}

typedef Go = void Function(Screen);

/// Screen identifiers for the app's flat navigation model.
enum Screen {
  home,
  schedule,
  rewards,
  impact,
  profile,
  history,
  badges,
  myQr,
  station,
  processing,
  success,
  failed,
  contributionDetail,
  leaderboard,
  facultyDetail,
  notifications,
  collectionCreated,
}
