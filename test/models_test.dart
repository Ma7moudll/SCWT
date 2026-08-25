import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

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

  group('material categories', () {
    test('only the four final categories are allowed', () {
      expect(validMaterialTypes, ['plastic', 'metal', 'paper', 'other']);
      expect(validMaterialTypes.length, 4);
      expect(validMaterialTypes, isNot(contains('glass')));
      expect(validMaterialTypes, isNot(contains('organic')));
    });

    test('every allowed material has a points value', () {
      for (final m in validMaterialTypes) {
        expect(
          pointsForMaterial(m),
          greaterThan(0),
          reason: '$m must award points',
        );
      }
    });

    test('points are case-insensitive', () {
      expect(pointsForMaterial('PLASTIC'), pointsForMaterial('plastic'));
      expect(pointsForMaterial(' Paper '), pointsForMaterial('paper'));
    });

    test('unknown materials fall back to the "other" value', () {
      expect(pointsForMaterial('glass'), pointsForMaterial('other'));
      expect(pointsForMaterial('organic'), pointsForMaterial('other'));
      expect(pointsForMaterial(''), pointsForMaterial('other'));
    });
  });

  group('recycling session', () {
    test(
      'Recycle Now starts a session in IDLE with the user attached',
      () async {
        await AppStore.instance.ensureLoaded();
        await AppStore.instance.signup(
          name: 'Emma Johnson',
          email: 'emma@campus.edu',
          studentId: 'ECO-2024-001',
        );
        AppStore.instance.prepareRecycle();
        final s = AppStore.instance.currentSession!;
        expect(s.status, SessionStatus.idle);
        expect(s.studentId, 'ECO-2024-001');
        expect(s.sessionId, isNotEmpty);
        expect(s.expiresAt.isAfter(s.startedAt), isTrue);
      },
    );

    test('selecting a station attaches it and moves to STATION_SELECTED', () {
      AppStore.instance.prepareRecycle();
      AppStore.instance.startRecycle(demoStations.first);
      expect(AppStore.instance.currentStation!.id, demoStations.first.id);
      expect(
        AppStore.instance.currentSession!.stationId,
        demoStations.first.id,
      );
      expect(
        AppStore.instance.currentSession!.status,
        SessionStatus.stationSelected,
      );
    });

    test('presenting the QR moves to WAITING_FOR_STUDENT_IDENTIFICATION', () {
      AppStore.instance.prepareRecycle();
      AppStore.instance.startRecycle(demoStations.first);
      AppStore.instance.showQrForDeposit();
      expect(
        AppStore.instance.currentSession!.status,
        SessionStatus.waitingForStudentIdentification,
      );
    });

    test('tablet identification moves to READY_FOR_DEPOSIT', () {
      AppStore.instance.prepareRecycle();
      AppStore.instance.startRecycle(demoStations.first);
      AppStore.instance.showQrForDeposit();
      AppStore.instance.confirmStationIdentification();
      expect(
        AppStore.instance.currentSession!.status,
        SessionStatus.readyForDeposit,
      );
    });

    test('session status lifecycle through completion', () {
      AppStore.instance.prepareRecycle();
      AppStore.instance.startRecycle(demoStations.first);
      AppStore.instance.updateSessionStatus(SessionStatus.processing);
      expect(
        AppStore.instance.currentSession!.status,
        SessionStatus.processing,
      );
      AppStore.instance.updateSessionStatus(SessionStatus.verifying);
      expect(AppStore.instance.currentSession!.status, SessionStatus.verifying);
      AppStore.instance.updateSessionStatus(SessionStatus.completed);
      expect(AppStore.instance.currentSession!.status, SessionStatus.completed);
    });

    test('session round-trips to/from json', () {
      AppStore.instance.prepareRecycle();
      AppStore.instance.startRecycle(demoStations.first);
      final s = AppStore.instance.currentSession!;
      final back = RecyclingSession.fromJson(s.toJson());
      expect(back.sessionId, s.sessionId);
      expect(back.stationId, s.stationId);
      expect(back.status, s.status);
      expect(
        back.startedAt.millisecondsSinceEpoch,
        s.startedAt.millisecondsSinceEpoch,
      );
    });
  });

  group('points awarded only after verification', () {
    test('creating a draft awards nothing', () async {
      await AppStore.instance.ensureLoaded();
      final before = AppStore.instance.points;
      AppStore.instance.newDraftContribution();
      expect(AppStore.instance.points, before);
    });

    test(
      'opening the QR / waiting for identification awards nothing',
      () async {
        await AppStore.instance.ensureLoaded();
        AppStore.instance.prepareRecycle();
        AppStore.instance.startRecycle(demoStations.first);
        AppStore.instance.showQrForDeposit();
        final before = AppStore.instance.points;
        AppStore.instance.confirmStationIdentification();
        expect(AppStore.instance.points, before);
      },
    );

    test('completed verified deposit awards the configured points', () async {
      await AppStore.instance.ensureLoaded();
      AppStore.instance.prepareRecycle();
      AppStore.instance.startRecycle(demoStations.first);
      final before = AppStore.instance.points;
      final draft = AppStore.instance.newDraftContribution();
      await AppStore.instance.completeVerifiedDeposit(draft);
      expect(AppStore.instance.points, before + draft.points);
      expect(
        AppStore.instance.points,
        before + pointsForMaterial(draft.materialType),
      );
      expect(AppStore.instance.currentContribution!.id, draft.id);
      expect(AppStore.instance.contributions.first.id, draft.id);
      expect(AppStore.instance.currentSession!.status, SessionStatus.completed);
    });

    test('failed session does not award points', () async {
      await AppStore.instance.ensureLoaded();
      AppStore.instance.prepareRecycle();
      AppStore.instance.startRecycle(demoStations.first);
      AppStore.instance.updateSessionStatus(SessionStatus.failed);
      final before = AppStore.instance.points;
      expect(AppStore.instance.currentSession!.status, SessionStatus.failed);
      expect(AppStore.instance.points, before);
    });
  });

  group('collection requests', () {
    test('creating a request returns a pending COL id', () async {
      await AppStore.instance.ensureLoaded();
      final req = await AppStore.instance.requestCollection(
        materialType: 'Plastic',
        estimatedQuantity: '5–10 kg',
        collectionPoint: 'Engineering Building',
        preferredDate: '18 Aug',
        timeWindow: '12:00 – 2:00 PM',
      );
      expect(req.id, startsWith('COL-2026-'));
      expect(req.status, CollectionStatus.pending);
      expect(req.statusLabel, 'Pending');
      expect(req.materialType, 'Plastic');
      expect(AppStore.instance.collectionRequests.first.id, req.id);
      expect(AppStore.instance.currentCollectionRequest!.id, req.id);
    });

    test('request round-trips to/from json', () async {
      await AppStore.instance.ensureLoaded();
      final req = await AppStore.instance.requestCollection(
        materialType: 'Paper',
        estimatedQuantity: '10–20 kg',
        collectionPoint: 'Library',
        preferredDate: '19 Aug',
        timeWindow: '2:00 – 4:00 PM',
      );
      final back = CollectionRequest.fromJson(req.toJson());
      expect(back.id, req.id);
      expect(back.materialType, req.materialType);
      expect(back.estimatedQuantity, req.estimatedQuantity);
      expect(back.collectionPoint, req.collectionPoint);
      expect(back.status, req.status);
      expect(
        back.requestedAt.millisecondsSinceEpoch,
        req.requestedAt.millisecondsSinceEpoch,
      );
    });

    test('requesting a collection does not award Smart Bin points', () async {
      await AppStore.instance.ensureLoaded();
      final before = AppStore.instance.points;
      await AppStore.instance.requestCollection(
        materialType: 'Metal',
        estimatedQuantity: '20–50 kg',
        collectionPoint: 'Main Gate',
        preferredDate: '20 Aug',
        timeWindow: '9:00 – 11:00 AM',
      );
      expect(AppStore.instance.points, before);
    });

    test('all collection statuses have labels', () {
      for (final s in CollectionStatus.values) {
        expect(s.name, isNotEmpty);
      }
      expect(CollectionStatus.values, isNotEmpty);
    });
  });

  group('contribution detail', () {
    test('new draft is a verified transaction in a valid category', () {
      final c = AppStore.instance.newDraftContribution();
      expect(validMaterialTypes, contains(c.materialType.toLowerCase()));
      expect(c.verificationStatus, 'DROP_CONFIRMED');
      expect(c.points, pointsForMaterial(c.materialType));
      expect(c.weight, greaterThan(0));
      expect(c.aiConfidence, inExclusiveRange(85, 100));
      expect(c.targetBin, '${c.materialType} Bin');
    });

    test('contribution round-trips to/from json', () {
      final c = AppStore.instance.newDraftContribution();
      final back = Contribution.fromJson(c.toJson());
      expect(back.id, c.id);
      expect(back.materialType, c.materialType);
      expect(back.weight, c.weight);
      expect(back.aiConfidence, c.aiConfidence);
      expect(back.points, c.points);
      expect(back.verificationStatus, c.verificationStatus);
      expect(
        back.timestamp.millisecondsSinceEpoch,
        c.timestamp.millisecondsSinceEpoch,
      );
    });
  });

  group('leaderboard', () {
    test('weekly leaderboard is ordered and complete', () {
      final entries = demoLeaderboard('Weekly');
      expect(entries.length, 6);
      expect(entries.first.facultyName, 'Engineering');
      expect(entries.first.rank, 1);
      for (var i = 1; i < entries.length; i++) {
        expect(entries[i - 1].points, greaterThan(entries[i].points));
      }
    });

    test('every period keeps a full ordered leaderboard', () {
      for (final period in ['Weekly', 'Monthly', 'All Time']) {
        final e = demoLeaderboard(period);
        expect(e.length, 6);
        expect(e.first.facultyName, 'Engineering');
      }
    });

    test('faculty mock data covers the six faculties', () {
      expect(demoFaculties.length, 6);
      expect(demoFaculties.map((f) => f.name), contains('Engineering'));
      for (final f in demoFaculties) {
        for (final c in f.recentContributions) {
          expect(validMaterialTypes, contains(c.materialType.toLowerCase()));
        }
      }
    });
  });
}
