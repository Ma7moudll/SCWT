import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:eclamp_flutter/models.dart';
import 'package:eclamp_flutter/repositories.dart';
import 'package:eclamp_flutter/screens.dart';
import 'package:eclamp_flutter/app_flow_nav.dart';
import 'package:eclamp_flutter/flow_screens.dart';
import 'package:eclamp_flutter/store.dart';
import 'package:eclamp_flutter/theme.dart';

final screens = {
  'home': (Screen.home, () {}),
  'schedule': (Screen.schedule, (_) {}),
  'rewards': (Screen.rewards, (_) {}),
  'impact': (Screen.impact, (_) {}),
  'profile': (Screen.profile, (_) {}),
  'history': (Screen.history, (_) {}),
  'badges': (Screen.badges, (_) {}),
  'myQr': (Screen.myQr, (_) {}),
  'station': (Screen.station, (_) {}),
  'processing': (Screen.processing, (_) {}),
  'success': (Screen.success, (_) {}),
  'failed': (Screen.failed, (_) {}),
  'contributionDetail': (Screen.contributionDetail, (_) {}),
  'leaderboard': (Screen.leaderboard, (_) {}),
  'facultyDetail': (Screen.facultyDetail, (_) {}),
  'notifications': (Screen.notifications, (_) {}),
  'collectionCreated': (Screen.collectionCreated, (_) {}),
};

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    AppStore.instance.currentSession = null;
    AppStore.instance.currentContribution = null;
    AppStore.instance.currentCollectionRequest = null;
    AppStore.instance.currentStation = null;
    AppStore.instance.currentFaculty = null;
  });

  for (final e in screens.entries) {
    testWidgets('${e.key} no overflow', (tester) async {
      tester.view.physicalSize = const Size(411 * 2, 800 * 2);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTheme(),
          home: Material(child: _wrap(e.value.$1)),
        ),
      );
      await tester.pump();
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
    'home quick actions: Recycle Now + Schedule Collection, no Scan',
    (tester) async {
      tester.view.physicalSize = const Size(411 * 2, 800 * 2);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.reset);
      final visited = <Screen>[];
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTheme(),
          home: Material(child: Home(go: visited.add)),
        ),
      );
      await tester.pump();
      expect(find.text('Recycle Now'), findsOneWidget);
      expect(
        find.text('Recycle your waste at an Ecolamp Smart Station'),
        findsOneWidget,
      );
      expect(find.text('Schedule Collection'), findsOneWidget);
      expect(find.text('Scan Station QR'), findsNothing);
      expect(find.text('Scan QR'), findsNothing);
      expect(find.text('Scan Now'), findsNothing);

      await tester.tap(find.text('Recycle Now'));
      await tester.pump();
      expect(visited.last, Screen.station);
      expect(AppStore.instance.currentSession, isNotNull);
      expect(AppStore.instance.currentSession!.status, SessionStatus.idle);
    },
  );

  testWidgets(
    'station selection hands off to the My QR (Ready to Recycle) state',
    (tester) async {
      tester.view.physicalSize = const Size(411 * 2, 800 * 2);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.reset);
      final visited = <Screen>[];
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTheme(),
          home: Material(child: StationSelect(go: visited.add)),
        ),
      );
      await tester.pump();

      await tester.tap(find.text('Engineering Station'));
      await tester.pump();
      expect(find.text('Show My QR at Station'), findsOneWidget);

      await tester.tap(find.text('Show My QR at Station'));
      await tester.pump();
      expect(visited.last, Screen.myQr);
      expect(
        AppStore.instance.currentSession!.status,
        SessionStatus.stationSelected,
      );
    },
  );

  testWidgets('ready to recycle waits for station, then ready to deposit', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(411 * 2, 800 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    AppStore.instance.prepareRecycle();
    AppStore.instance.startRecycle(demoStations.first);

    final visited = <Screen>[];
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: Material(child: MyQr(go: visited.add)),
      ),
    );
    await tester.pump();

    expect(find.text('Ready to Recycle'), findsOneWidget);
    expect(
      find.textContaining('Show this QR code to the station tablet'),
      findsOneWidget,
    );
    expect(find.text('Waiting for station…'), findsOneWidget);
    expect(
      AppStore.instance.currentSession!.status,
      SessionStatus.waitingForStudentIdentification,
    );

    await tester.ensureVisible(find.text('Station scanned my QR'));
    await tester.tap(find.text('Station scanned my QR'));
    await tester.pump();

    expect(
      AppStore.instance.currentSession!.status,
      SessionStatus.readyForDeposit,
    );
    expect(find.text('Ready to Deposit'), findsOneWidget);
    expect(find.text('Start Recycling'), findsOneWidget);

    await tester.ensureVisible(find.text('Start Recycling'));
    await tester.tap(find.text('Start Recycling'));
    await tester.pump();
    expect(visited.last, Screen.processing);
  });

  testWidgets(
    'schedule collection flow creates a request and shows the created screen',
    (tester) async {
      tester.view.physicalSize = const Size(411 * 2, 1000 * 2);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.reset);
      final visited = <Screen>[];
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTheme(),
          home: Material(child: ScheduleCollection(go: visited.add)),
        ),
      );
      await tester.pump();

      expect(find.text('Plastic'), findsOneWidget);
      expect(find.text('Metal'), findsOneWidget);
      expect(find.text('Paper'), findsOneWidget);
      expect(find.text('Other'), findsOneWidget);
      expect(find.text('Glass'), findsNothing);

      await tester.ensureVisible(find.text('Request Collection'));
      await tester.tap(find.text('Request Collection'));
      await tester.pump();
      await tester.pump();

      expect(visited.last, Screen.collectionCreated);
      expect(AppStore.instance.collectionRequests, isNotEmpty);
      expect(
        AppStore.instance.currentCollectionRequest!.id,
        startsWith('COL-2026-'),
      );
      expect(
        AppStore.instance.currentCollectionRequest!.status,
        CollectionStatus.pending,
      );
      expect(
        AppStore.instance.points,
        0,
        reason: 'collection request never awards points',
      );
    },
  );

  testWidgets('collection created shows request summary and pending status', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(411 * 2, 800 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    await AppStore.instance.ensureLoaded();
    await AppStore.instance.requestCollection(
      materialType: 'Plastic',
      estimatedQuantity: '5–10 kg',
      collectionPoint: 'Engineering Building',
      preferredDate: '18 Aug',
      timeWindow: '12:00 – 2:00 PM',
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: Material(child: CollectionCreated(go: _go)),
      ),
    );
    await tester.pump();

    expect(find.text('Collection Request Created'), findsOneWidget);
    expect(find.text('Request ID'), findsOneWidget);
    expect(find.text('Pending'), findsOneWidget);
    expect(find.textContaining('COL-2026-'), findsWidgets);
    expect(find.text('5–10 kg'), findsWidgets);
    expect(find.text('Engineering Building'), findsWidgets);
  });

  testWidgets('processing shows the five verification stages', (tester) async {
    tester.view.physicalSize = const Size(411 * 2, 1200 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: Material(child: const Processing(go: _go)),
      ),
    );
    await tester.pump();
    expect(find.text('Identifying'), findsOneWidget);
    expect(find.text('Classifying'), findsOneWidget);
    expect(find.text('Sorting'), findsOneWidget);
    expect(find.text('Verifying'), findsOneWidget);
    expect(find.text('Completed'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

Widget _wrap(Screen s) {
  switch (s) {
    case Screen.home:
    case Screen.history:
    case Screen.rewards:
    case Screen.profile:
      return _Shell(pre: _bodyOf(s));
    default:
      return _bodyOf(s);
  }
}

Widget _bodyOf(Screen s) {
  switch (s) {
    case Screen.home:
      return const Home(go: _go);
    case Screen.schedule:
      return const ScheduleCollection(go: _go);
    case Screen.rewards:
      return const Rewards(go: _go);
    case Screen.impact:
      return const Impact(go: _go);
    case Screen.profile:
      return const Profile(go: _go);
    case Screen.history:
      return const History(go: _go);
    case Screen.badges:
      return const Badges(go: _go);
    case Screen.myQr:
      return const MyQr(go: _go);
    case Screen.station:
      return const StationSelect(go: _go);
    case Screen.processing:
      return const Processing(go: _go);
    case Screen.success:
      return const RecyclingResult(success: true, go: _go);
    case Screen.failed:
      return const RecyclingResult(success: false, go: _go);
    case Screen.contributionDetail:
      return const ContributionDetail(go: _go);
    case Screen.leaderboard:
      return const Leaderboard(go: _go);
    case Screen.facultyDetail:
      return const FacultyDetail(go: _go);
    case Screen.notifications:
      return const Notifications(go: _go);
    case Screen.collectionCreated:
      return const CollectionCreated(go: _go);
  }
}

void _go(Screen s) {}

class _Shell extends StatelessWidget {
  const _Shell({required this.pre});
  final Widget pre;
  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.background,
      child: Material(
        color: AppColors.background,
        child: Stack(
          children: [
            pre,
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: Container(
                decoration: const BoxDecoration(
                  color: AppColors.card,
                  border: Border(top: BorderSide(color: Color(0xFFe5efe9))),
                ),
                padding: const EdgeInsets.fromLTRB(10, 8, 10, 10),
                child: Row(
                  children: navItems.map((item) {
                    return Expanded(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            item.$3,
                            size: 18,
                            color: const Color(0xFF7e8d86),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            item.$2,
                            style: const TextStyle(
                              fontSize: 10,
                              color: Color(0xFF7e8d86),
                            ),
                          ),
                        ],
                      ),
                    );
                  }).toList(),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

void splashLogin() {
  testWidgets('splash no overflow', (tester) async {
    tester.view.physicalSize = const Size(411 * 2, 800 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: const Splash(onStart: _go0),
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
  testWidgets('login no overflow', (tester) async {
    tester.view.physicalSize = const Size(411 * 2, 800 * 2);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: Login(onBack: _go0, onSignup: _go0, onSuccess: _go0),
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
}

void _go0() {}
void main2() {}
