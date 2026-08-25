import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:eclamp_flutter/badges.dart';
import 'package:eclamp_flutter/impact.dart';
import 'package:eclamp_flutter/models.dart';
import 'package:eclamp_flutter/repositories.dart';
import 'package:eclamp_flutter/store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    AppStore.instance.currentSession = null;
    AppStore.instance.currentContribution = null;
    AppStore.instance.currentCollectionRequest = null;
    AppStore.instance.currentStation = null;
    AppStore.instance.currentFaculty = null;
  });

  group('authentication session', () {
    test('signup creates and persists the user', () async {
      await AppStore.instance.ensureLoaded();
      expect(AppStore.instance.isLoggedIn, isFalse);
      await AppStore.instance.signup(
        name: 'Emma Johnson',
        email: 'emma@campus.edu',
        studentId: 'ECO-2024-001',
      );
      expect(AppStore.instance.isLoggedIn, isTrue);
      expect(AppStore.instance.user!.initials, 'EJ');
      expect(AppStore.instance.user!.firstName, 'Emma');
    });

    test('login derives a session for an unknown local account', () async {
      await AppStore.instance.ensureLoaded();
      await AppStore.instance.login(email: 'sam@campus.edu');
      expect(AppStore.instance.isLoggedIn, isTrue);
      expect(AppStore.instance.user!.email, 'sam@campus.edu');
      expect(AppStore.instance.user!.studentId, startsWith('ECO-'));
    });

    test('session survives an app restart', () async {
      await AppStore.instance.ensureLoaded();
      await AppStore.instance.signup(
        name: 'Emma Johnson',
        email: 'emma@campus.edu',
        studentId: 'ECO-2024-001',
      );
      // Fresh store instance would read from prefs on restart:
      final fresh = AppStore.freshForTest();
      await fresh.ensureLoaded();
      expect(fresh.isLoggedIn, isTrue);
      expect(fresh.user!.name, 'Emma Johnson');
    });

    test('logout clears session AND all user data', () async {
      await AppStore.instance.ensureLoaded();
      await AppStore.instance.signup(
        name: 'Emma Johnson',
        email: 'emma@campus.edu',
        studentId: 'ECO-2024-001',
      );
      AppStore.instance.prepareRecycle();
      AppStore.instance.startRecycle(demoStations.first);
      final draft = AppStore.instance.newDraftContribution();
      await AppStore.instance.completeVerifiedDeposit(draft);
      await AppStore.instance.requestCollection(
        materialType: 'Paper',
        estimatedQuantity: '5–10 kg',
        collectionPoint: 'Library',
        preferredDate: '1 Jan',
        timeWindow: '9:00 – 11:00 AM',
      );
      expect(AppStore.instance.points, greaterThan(0));
      expect(AppStore.instance.contributions, isNotEmpty);

      await AppStore.instance.logout();

      expect(AppStore.instance.isLoggedIn, isFalse);
      expect(AppStore.instance.user, isNull);
      expect(AppStore.instance.points, 0);
      expect(AppStore.instance.contributions, isEmpty);
      expect(AppStore.instance.collectionRequests, isEmpty);
      expect(AppStore.instance.notifications, isEmpty);
      expect(AppStore.instance.currentSession, isNull);
      expect(AppStore.instance.currentStation, isNull);
    });
  });

  group('honest account state', () {
    test(
      'a new account has zero points and no history or notifications',
      () async {
        await AppStore.instance.ensureLoaded();
        await AppStore.instance.signup(
          name: 'New User',
          email: 'new@campus.edu',
          studentId: 'ECO-9999-001',
        );
        expect(AppStore.instance.points, 0);
        expect(AppStore.instance.contributions, isEmpty);
        expect(AppStore.instance.notifications, isEmpty);
      },
    );

    test('deposit persists across restart exactly once', () async {
      await AppStore.instance.ensureLoaded();
      await AppStore.instance.signup(
        name: 'Emma Johnson',
        email: 'emma@campus.edu',
        studentId: 'ECO-2024-001',
      );
      AppStore.instance.prepareRecycle();
      AppStore.instance.startRecycle(demoStations.first);
      final draft = AppStore.instance.newDraftContribution();
      await AppStore.instance.completeVerifiedDeposit(draft);
      final pointsAfterDeposit = AppStore.instance.points;

      final fresh = AppStore.freshForTest();
      await fresh.ensureLoaded();
      expect(fresh.points, pointsAfterDeposit);
      expect(fresh.contributions.length, 1);
      expect(fresh.notifications.length, 1);
    });
  });

  group('rewards redemption', () {
    setUp(() async {
      await AppStore.instance.ensureLoaded();
      // Reset any state left over from previous tests/groups.
      await AppStore.instance.logout();
      await AppStore.instance.signup(
        name: 'Emma Johnson',
        email: 'emma@campus.edu',
        studentId: 'ECO-2024-001',
      );
    });

    test('insufficient balance is rejected without deducting', () async {
      expect(AppStore.instance.points, 0);
      final r = await AppStore.instance.redeemReward(
        rewardId: 'test',
        cost: 500,
      );
      expect(r, RedeemResult.insufficientPoints);
      expect(AppStore.instance.points, 0);
    });

    test('successful redemption deducts points once', () async {
      AppStore.instance.prepareRecycle();
      AppStore.instance.startRecycle(demoStations.first);
      var guard = 0;
      while (AppStore.instance.points < 30 && guard < 20) {
        await AppStore.instance.completeVerifiedDeposit(
          AppStore.instance.newDraftContribution(),
        );
        guard++;
      }
      final before = AppStore.instance.points;
      expect(before, greaterThanOrEqualTo(30));

      final r = await AppStore.instance.redeemReward(
        rewardId: 'eco_store_20',
        cost: 30,
      );
      expect(r, RedeemResult.success);
      expect(AppStore.instance.points, before - 30);

      final fresh = AppStore.freshForTest();
      await fresh.ensureLoaded();
      expect(fresh.points, before - 30);
    });
  });

  group('badges are deterministic', () {
    test('locked with no activity, unlocked by real thresholds', () {
      expect(evaluateBadges([]).values.every((v) => v == false), isTrue);

      final first = [
        Contribution(
          id: 'c1',
          materialType: 'plastic',
          weight: 100,
          aiConfidence: 90,
          targetBin: 'Plastic Bin',
          points: 10,
          stationId: 'ST-001',
          timestamp: DateTime(2026, 8, 1),
        ),
      ];
      final m = evaluateBadges(first);
      expect(m['first_recycle'], isTrue);
      expect(m['ten_kg'], isFalse);
      expect(m['green_champion'], isFalse);

      final big = List.generate(
        26,
        (i) => Contribution(
          id: 'c$i',
          materialType: 'metal',
          weight: 500,
          aiConfidence: 90,
          targetBin: 'Metal Bin',
          points: 15,
          stationId: 'ST-001',
          timestamp: DateTime(2026, 8, 2),
        ),
      );
      final mb = evaluateBadges(big);
      // 26 deposits x 500 g = 13 kg; points = 390 (< 500)
      expect(mb['first_recycle'], isTrue);
      expect(mb['ten_kg'], isTrue);
      expect(mb['eco_warrior'], isTrue);
      expect(mb['green_champion'], isFalse);
    });
  });

  group('impact calculator', () {
    test('derives totals from real contributions', () {
      final now = DateTime(2026, 8, 25);
      final summary = ImpactCalculator.summarize([
        _c('plastic', 1200, 10, now),
        _c('paper', 800, 8, now),
        _c('metal', 500, 15, DateTime(2026, 7, 20)),
      ], now: now);
      expect(summary.totalWeightKg, closeTo(2.5, 0.001));
      expect(summary.depositCount, 3);
      expect(summary.pointsEarned, 33);
      expect(summary.weekPoints, 18); // only the two recent ones
      expect(summary.monthWeightKg, closeTo(2.0, 0.001)); // August only
      expect(summary.byMaterial.first.material, 'Plastic'); // largest first
      expect(summary.co2Kg, closeTo(2.5 * 2.5, 0.001));
    });

    test('empty history produces zeroed summary', () {
      final s = ImpactCalculator.summarize([]);
      expect(s.totalWeightKg, 0);
      expect(s.depositCount, 0);
      expect(s.byMaterial, isEmpty);
      expect(s.estimatedValueEgp, 0);
    });
  });

  group('session expiry', () {
    test('fresh session is not expired', () async {
      await AppStore.instance.ensureLoaded();
      AppStore.instance.prepareRecycle();
      expect(AppStore.instance.isCurrentSessionExpired(), isFalse);
    });

    test('expired session flags as expired', () async {
      await AppStore.instance.ensureLoaded();
      final s = AppStore.instance.prepareRecycle();
      AppStore.instance.currentSession = s.copyWith(
        status: SessionStatus.stationSelected,
      );
      // Force expiry into the past.
      final expired = RecyclingSession(
        sessionId: s.sessionId,
        studentId: s.studentId,
        stationId: s.stationId,
        startedAt: s.startedAt,
        expiresAt: DateTime.now().subtract(const Duration(minutes: 1)),
        status: s.status,
      );
      AppStore.instance.currentSession = expired;
      expect(AppStore.instance.isCurrentSessionExpired(), isTrue);
      AppStore.instance.expireCurrentSession();
      expect(AppStore.instance.currentSession!.status, SessionStatus.expired);
    });
  });
}

Contribution _c(String material, double grams, int pts, DateTime at) =>
    Contribution(
      id: 'x-$material-$grams',
      materialType: material,
      weight: grams,
      aiConfidence: 90,
      targetBin: '$material Bin',
      points: pts,
      stationId: 'ST-001',
      timestamp: at,
      verificationStatus: 'DROP_CONFIRMED',
    );
