import 'package:flutter/material.dart' show Icons;
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:eclamp_flutter/api/backend_gateway.dart';
import 'package:eclamp_flutter/api/contract.dart';
import 'package:eclamp_flutter/models.dart';
import 'package:eclamp_flutter/store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    AppStore.instance.currentSession = null;
    AppStore.instance.currentContribution = null;
  });

  group('wire contract mappers', () {
    test('user wire → UserAccount', () {
      final u = userFromWire({
        'id': 'u-1',
        'studentCode': 'S-2026-001',
        'name': 'Sara Ali',
        'facultyId': 'ENGINEERING',
        'facultyName': 'Faculty of Engineering',
        'points': 42,
      }, fallbackEmail: 'sara@campus.edu');
      expect(u.name, 'Sara Ali');
      expect(u.studentId, 'S-2026-001');
      expect(u.email, 'sara@campus.edu');
      expect(pointsFromWire({'points': 42}), 42);
      expect(pointsFromWire({}), 0);
    });

    test('station wire maps availability without mechanical vocabulary', () {
      final online = stationFromWire({
        'id': 'st-1',
        'station_code': 'ST-001',
        'name': 'Engineering Station',
        'status': 'online',
        'mechanism_position': 2,
      });
      expect(online.status, StationStatus.online);
      expect(online.availability, 'Available');

      final offline = stationFromWire({
        'id': 'st-2',
        'station_code': 'ST-002',
        'name': 'Library Station',
        'status': 'offline',
      });
      expect(offline.status, StationStatus.offline);
      expect(offline.availability, 'Unavailable');
    });

    test('history items map to authoritative contributions', () {
      final items = contributionsFromHistoryWire([
        {
          'id': 'we-1',
          'operation_id': 'OP-20260817-000001',
          'station_id': 'st-001',
          'predicted_class': 'plastic',
          'weight_g': 18.4,
          'points_awarded': 5,
          'created_at': '2026-08-17T10:00:00Z',
        },
      ]);
      expect(items, hasLength(1));
      expect(items.first.id, 'OP-20260817-000001');
      expect(items.first.materialType, 'Plastic');
      expect(items.first.weight, 18.4);
      expect(items.first.points, 5);
      expect(items.first.verificationStatus, 'CONFIRMED');
    });

    test('deposit wire statuses map onto the verification stages', () {
      expect(WireDepositStatus.capture.processingStage, 0);
      expect(WireDepositStatus.analyzing.processingStage, 1);
      expect(WireDepositStatus.routing.processingStage, 2);
      expect(WireDepositStatus.moving.processingStage, 2);
      expect(WireDepositStatus.measuring.processingStage, 3);
      expect(WireDepositStatus.confirmed.processingStage, 4);

      expect(WireDepositStatus.confirmed.isTerminal, isTrue);
      expect(WireDepositStatus.rejected.isTerminal, isTrue);
      expect(WireDepositStatus.routing.isTerminal, isFalse);
      expect(WireDepositStatus.tryFrom('nonsense'), WireDepositStatus.pending);
    });

    test('terminal deposit becomes an authoritative contribution', () {
      const json = {
        'operation_id': 'OP-20260817-000009',
        'prediction_id': '',
        'station_id': 'st-001',
        'predicted_class': 'metal',
        'expected_position': 2,
        'actual_position': 2,
        'confidence': 0.97,
        'confidence_level': 'high',
        'weight_g': 42.0,
        'mechanical_confirmed': true,
        'potential_points': 15,
        'points_awarded': 15,
        'status': 'confirmed',
        'reject_reason': null,
        'expires_at': '2026-08-17T10:05:00Z',
      };
      final dep = WireDeposit.fromJson(json);
      expect(dep.isTerminal, isTrue);
      expect(dep.pointsAwarded, 15);
      final c = dep.toContribution();
      expect(c.materialType, 'Metal');
      expect(c.points, 15);
      expect(c.aiConfidence, closeTo(97, 0.01));
      expect(c.verificationStatus, 'CONFIRMED');
    });

    test('leaderboard wire preserves order as rank', () {
      final entries = leaderboardFromWire([
        {
          'id': 'eng',
          'name': 'Engineering',
          'detail': '1240 kg recovered',
          'points': 12450,
        },
        {'id': 'sci', 'name': 'Science', 'detail': '1110 kg', 'points': 11820},
      ]);
      expect(entries.first.rank, 1);
      expect(entries.last.rank, 2);
      expect(entries.first.weightKg, 1240);
      expect(entries.first.facultyId, 'eng');
    });

    test('handoff QR payload contains only the single-use token', () {
      final payload = BackendGateway.handoffQrPayload('abc123def456');
      expect(payload, 'ECOLOOP:HANDOFF:abc123def456');
      expect(payload.contains('password'), isFalse);
    });
  });

  group('backend rewards catalog mapping', () {
    test('reward wire maps cost/name/destination flag', () {
      final r = BackendReward.fromJson({
        'id': 'vod_cash_10',
        'category': 'cash',
        'name': 'Vodafone Cash 10 EGP',
        'provider': 'Vodafone',
        'points_cost': 250,
        'value_label': '10 EGP',
        'icon': 'account_balance_wallet',
        'requires_destination': true,
      });
      expect(r.pointsCost, 250);
      expect(r.requiresDestination, isTrue);
      expect(
        rewardIcon('account_balance_wallet'),
        Icons.account_balance_wallet,
      );
      expect(rewardIcon('unknown-name'), Icons.redeem); // safe fallback
    });

    test('rewardsFromWire maps the catalog list', () {
      final list = rewardsFromWire([
        {'id': 'a', 'points_cost': 100},
        {'id': 'b', 'points_cost': 200, 'icon': 'print'},
      ]);
      expect(list.length, 2);
      expect(list[1].pointsCost, 200);
      expect(list[1].id, 'b');
    });
  });

  group('backend-mode store hooks never award points locally', () {
    test('setBackendUser applies the authoritative balance', () async {
      await AppStore.instance.ensureLoaded();
      await AppStore.instance.setBackendUser(
        const UserAccount(
          name: 'Sara Ali',
          email: 'sara@campus.edu',
          studentId: 'S-1',
        ),
        points: 77,
      );
      expect(AppStore.instance.isLoggedIn, isTrue);
      expect(AppStore.instance.isBackendMode, isTrue);
      expect(AppStore.instance.points, 77);
    });

    test(
      'applyAuthoritativeDeposit records history WITHOUT touching points',
      () async {
        await AppStore.instance.ensureLoaded();
        await AppStore.instance.setBackendUser(
          const UserAccount(
            name: 'Sara Ali',
            email: 'sara@campus.edu',
            studentId: 'S-1',
          ),
          points: 100,
        );
        await AppStore.instance.applyAuthoritativeDeposit(
          _c(points: 15),
          stationName: 'Engineering Station',
        );
        // Points unchanged — the backend owns them; sync reconciles.
        expect(AppStore.instance.points, 100);
        expect(AppStore.instance.contributions.first.points, 15);
        expect(AppStore.instance.notifications.first.title, contains('15'));
      },
    );
  });
}

Contribution _c({required int points}) => Contribution(
  id: 'OP-X',
  materialType: 'Metal',
  weight: 40,
  aiConfidence: 95,
  targetBin: 'Metal Bin',
  points: points,
  stationId: 'st-001',
  timestamp: DateTime(2026, 8, 25),
  verificationStatus: 'CONFIRMED',
);

