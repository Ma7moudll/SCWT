import 'package:flutter/material.dart';

import 'api/app_config.dart';
import 'api/backend_gateway.dart';
import 'app_flow_nav.dart';
import 'flow_screens.dart';
import 'screens.dart';
import 'store.dart';
import 'theme.dart';

void main() {
  runApp(const EcolampApp());
}

class EcolampApp extends StatelessWidget {
  const EcolampApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Ecolamp',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: const AppFlow(),
    );
  }
}

class AppFlow extends StatefulWidget {
  const AppFlow({super.key});
  @override
  State<AppFlow> createState() => _AppFlowState();
}

class _AppFlowState extends State<AppFlow> {
  bool _loaded = false;
  bool started = false;
  bool authenticated = false;
  bool login = true;
  Screen screen = Screen.home;

  @override
  void initState() {
    super.initState();
    AppFlowNav.provide(_go, onLogout: _onLogout);
    AppStore.instance.ensureLoaded().then((_) async {
      if (!mounted) return;
      var authenticated = false;
      if (AppConfig.isProduction) {
        // Production: restore a real backend session (JWT in secure storage).
        authenticated = await BackendGateway.instance.restoreSession();
        if (authenticated) {
          try {
            await BackendGateway.instance.syncFromBackend();
          } catch (_) {
            // Backend briefly unreachable — the restored session still holds;
            // screens will show cached data and can refresh later.
          }
        }
      }
      if (!mounted) return;
      setState(() {
        this.authenticated = authenticated;
        _loaded = true;
      });
    });
  }

  void _go(Screen s) => setState(() => screen = s);

  /// Called after logout (local or backend): drops back to the Login screen.
  void _onLogout() {
    AppFlowNav.provide(_go, onLogout: _onLogout);
    setState(() {
      authenticated = false;
      login = true;
      started = true;
      screen = Screen.home;
    });
  }

  Widget _buildAuth() {
    if (login) {
      return Login(
        onBack: () => setState(() => started = false),
        onSignup: () => setState(() => login = false),
        onSuccess: () => setState(() => authenticated = true),
      );
    }
    return Signup(
      onBack: () => setState(() => started = false),
      onLogin: () => setState(() => login = true),
      onSuccess: () => setState(() {
        login = true;
        // Demo mode: local signup authenticates immediately. Production:
        // register only CREATES the account — an explicit login follows.
        authenticated = !AppConfig.isProduction;
      }),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      return const ColoredBox(color: Colors.white, child: SizedBox.shrink());
    }
    if (!started && !authenticated) {
      return Splash(onStart: () => setState(() => started = true));
    }
    if (!authenticated) {
      return _buildAuth();
    }
    return _AppShell(screen: screen, go: _go);
  }
}

class _AppShell extends StatelessWidget {
  const _AppShell({required this.screen, required this.go});
  final Screen screen;
  final Go go;

  @override
  Widget build(BuildContext context) {
    final bottomScreens = {
      Screen.home,
      Screen.history,
      Screen.rewards,
      Screen.profile,
    };
    Widget body;
    switch (screen) {
      case Screen.home:
        body = Home(go: go);
      case Screen.schedule:
        body = ScheduleCollection(go: go);
      case Screen.rewards:
        body = Rewards(go: go);
      case Screen.impact:
        body = Impact(go: go);
      case Screen.profile:
        body = Profile(go: go);
      case Screen.history:
        body = History(go: go);
      case Screen.badges:
        body = Badges(go: go);
      case Screen.myQr:
        body = MyQr(go: go);
      case Screen.collectionCreated:
        body = CollectionCreated(go: go);
      case Screen.station:
        body = StationSelect(go: go);
      case Screen.processing:
        body = Processing(go: go);
      case Screen.success:
        body = RecyclingResult(success: true, go: go);
      case Screen.failed:
        body = RecyclingResult(success: false, go: go);
      case Screen.contributionDetail:
        body = ContributionDetail(go: go);
      case Screen.leaderboard:
        body = Leaderboard(go: go);
      case Screen.facultyDetail:
        body = FacultyDetail(go: go);
      case Screen.notifications:
        body = Notifications(go: go);
    }
    return Container(
      color: AppColors.background,
      child: Material(
        color: AppColors.background,
        child: Stack(
          children: [
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 200),
              child: KeyedSubtree(key: ValueKey(screen), child: body),
            ),
            if (bottomScreens.contains(screen))
              Positioned(
                left: 0,
                right: 0,
                bottom: 0,
                child: _BottomNav(screen: screen, go: go),
              ),
          ],
        ),
      ),
    );
  }
}

class _BottomNav extends StatelessWidget {
  const _BottomNav({required this.screen, required this.go});
  final Screen screen;
  final Go go;
  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: AppColors.card,
        border: Border(top: BorderSide(color: Color(0xFFe5efe9))),
      ),
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 10),
      child: Row(
        children: navItems.map((item) {
          final active = item.$1 == screen;
          final color = active
              ? const Color(0xFF19a754)
              : const Color(0xFF7e8d86);
          return Expanded(
            child: InkWell(
              onTap: () => go(item.$1),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(active ? item.$3 : item.$4, size: 18, color: color),
                  const SizedBox(height: 4),
                  Text(
                    item.$2,
                    style: TextStyle(
                      fontSize: 10,
                      color: color,
                      fontWeight: active ? FontWeight.w800 : FontWeight.w500,
                    ),
                  ),
                ],
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}
