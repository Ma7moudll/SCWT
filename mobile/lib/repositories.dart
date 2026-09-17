import 'models.dart';

/// Repository contracts so a real FastAPI backend can be plugged in later
/// without touching the UI layer.
///
/// Future endpoints:
///   POST /auth/login            -> AuthRepository.login
///   POST /auth/signup           -> AuthRepository.signup
///   GET  /me                    -> UserRepository.me
///   GET  /me/points             -> UserRepository.points
///   GET  /me/history            -> UserRepository.history
///   GET  /me/badges             -> UserRepository.badges
///   GET  /leaderboard           -> LeaderboardRepository.leaderboard
///   GET  /faculties             -> LeaderboardRepository.faculties
///   POST /deposit/session       -> WasteRepository.startSession
///   POST /deposit               -> WasteRepository.deposit
///   POST /deposit/confirm       -> WasteRepository.confirm
///   POST /collection/request    -> (future) bulk campus collection
///   GET  /bins/status           -> StationRepository.stations
abstract interface class AuthRepository {
  Future<void> login(String studentId, String phone);
  Future<void> signup(String studentId, String phone);
}

abstract interface class UserRepository {
  Future<int> points();
  Future<List<Contribution>> history();
  Future<({String name, String studentId, String faculty})> me();
}

abstract interface class WasteRepository {
  Future<String> startSession();
  Future<Contribution> deposit(String sessionId, Contribution draft);
  Future<Contribution> confirm(String sessionId, Contribution contribution);
}

abstract interface class LeaderboardRepository {
  Future<List<LeaderboardEntry>> leaderboard(String period);
  Future<List<Faculty>> faculties();
}

abstract interface class StationRepository {
  Future<List<Station>> stations();
}

// ---------------------------------------------------------------------------
// Local/mock implementations — THE single place holding demo data until a
// backend exists. UI reads through [AppRepositories] so swapping to real
// implementations touches only this file.
// ---------------------------------------------------------------------------

class MockRepositories
    implements
        AuthRepository,
        UserRepository,
        WasteRepository,
        LeaderboardRepository,
        StationRepository {
  @override
  Future<void> login(String studentId, String phone) async =>
      await Future<void>.value();

  @override
  Future<void> signup(String studentId, String phone) async =>
      await Future<void>.value();

  @override
  Future<int> points() async => 0;

  @override
  Future<({String name, String studentId, String faculty})> me() async => (
    name: 'SCWT Student',
    studentId: 'ECO-0000-000',
    faculty: 'Engineering',
  );

  @override
  Future<List<Contribution>> history() async => [];

  @override
  Future<String> startSession() async =>
      'sess-${DateTime.now().millisecondsSinceEpoch}';

  @override
  Future<Contribution> deposit(String sessionId, Contribution draft) async =>
      draft;

  @override
  Future<Contribution> confirm(
    String sessionId,
    Contribution contribution,
  ) async => contribution;

  @override
  Future<List<LeaderboardEntry>> leaderboard(String period) async =>
      demoLeaderboard(period);

  @override
  Future<List<Faculty>> faculties() async => demoFaculties;

  @override
  Future<List<Station>> stations() async => demoStations;
}

/// Access point for data repositories. Currently returns the local demo
/// implementation; replace with networked implementations when the backend
/// ships. The *Sync accessors expose the local dataset synchronously — call
/// sites must migrate to the async repository interfaces at integration time.
class AppRepositories {
  AppRepositories._();
  static final AppRepositories instance = AppRepositories._();

  final MockRepositories _impl = MockRepositories();

  LeaderboardRepository get leaderboard => _impl;
  StationRepository get stations => _impl;
  UserRepository get user => _impl;
  WasteRepository get waste => _impl;
  AuthRepository get auth => _impl;

  // Local synchronous datasets (demo/faculty data is NOT user-specific).
  List<LeaderboardEntry> leaderboardSync(String period) =>
      demoLeaderboard(period);
  List<Faculty> facultiesSync() => demoFaculties;
  List<Station> stationsSync() => demoStations;
}

// ---------------------------------------------------------------------------
// Demo data (isolated here ONLY — never presented as the user's own activity)
// ---------------------------------------------------------------------------

List<LeaderboardEntry> demoLeaderboard(String period) {
  final delta = period == 'Weekly'
      ? 0
      : period == 'Monthly'
      ? 1200
      : 6200;
  return [
    LeaderboardEntry(
      facultyId: 'eng',
      facultyName: 'Engineering',
      rank: 1,
      points: 12450 + delta,
      weightKg: 1240,
    ),
    LeaderboardEntry(
      facultyId: 'sci',
      facultyName: 'Science',
      rank: 2,
      points: 11820 + delta,
      weightKg: 1110,
    ),
    LeaderboardEntry(
      facultyId: 'com',
      facultyName: 'Commerce',
      rank: 3,
      points: 9760 + delta,
      weightKg: 920,
    ),
    LeaderboardEntry(
      facultyId: 'lit',
      facultyName: 'Arts & Literature',
      rank: 4,
      points: 8340 + delta,
      weightKg: 760,
    ),
    LeaderboardEntry(
      facultyId: 'med',
      facultyName: 'Medicine',
      rank: 5,
      points: 7210 + delta,
      weightKg: 640,
    ),
    LeaderboardEntry(
      facultyId: 'law',
      facultyName: 'Law',
      rank: 6,
      points: 5980 + delta,
      weightKg: 510,
    ),
  ];
}

final demoFaculties = <Faculty>[
  Faculty(
    id: 'eng',
    name: 'Engineering',
    rank: 1,
    points: 12450,
    weightKg: 1240,
    students: 1240,
    weeklyProgress: 0.78,
    recentContributions: [
      Contribution(
        id: 'EL-2026-000124',
        materialType: 'Plastic',
        weight: 18.4,
        aiConfidence: 94,
        targetBin: 'Plastic Bin',
        points: 10,
        stationId: 'ST-001',
        timestamp: _t1,
      ),
      Contribution(
        id: 'EL-2026-000123',
        materialType: 'Metal',
        weight: 42.0,
        aiConfidence: 92,
        targetBin: 'Metal Bin',
        points: 15,
        stationId: 'ST-001',
        timestamp: _t2,
      ),
      Contribution(
        id: 'EL-2026-000121',
        materialType: 'Paper',
        weight: 66.2,
        aiConfidence: 97,
        targetBin: 'Paper Bin',
        points: 8,
        stationId: 'ST-002',
        timestamp: _t3,
      ),
    ],
  ),
  Faculty(
    id: 'sci',
    name: 'Science',
    rank: 2,
    points: 11820,
    weightKg: 1110,
    students: 1085,
    weeklyProgress: 0.71,
    recentContributions: [
      Contribution(
        id: 'EL-2026-000120',
        materialType: 'Plastic',
        weight: 24.1,
        aiConfidence: 95,
        targetBin: 'Plastic Bin',
        points: 12,
        stationId: 'ST-005',
        timestamp: _t1,
      ),
    ],
  ),
  Faculty(
    id: 'com',
    name: 'Commerce',
    rank: 3,
    points: 9760,
    weightKg: 920,
    students: 1330,
    weeklyProgress: 0.64,
    recentContributions: [
      Contribution(
        id: 'EL-2026-000118',
        materialType: 'Paper',
        weight: 51.7,
        aiConfidence: 96,
        targetBin: 'Paper Bin',
        points: 8,
        stationId: 'ST-003',
        timestamp: _t2,
      ),
    ],
  ),
  Faculty(
    id: 'lit',
    name: 'Arts & Literature',
    rank: 4,
    points: 8340,
    weightKg: 760,
    students: 540,
    weeklyProgress: 0.55,
    recentContributions: [],
  ),
  Faculty(
    id: 'med',
    name: 'Medicine',
    rank: 5,
    points: 7210,
    weightKg: 640,
    students: 980,
    weeklyProgress: 0.48,
    recentContributions: [],
  ),
  Faculty(
    id: 'law',
    name: 'Law',
    rank: 6,
    points: 5980,
    weightKg: 510,
    students: 440,
    weeklyProgress: 0.41,
    recentContributions: [],
  ),
];

final _t1 = DateTime(2026, 8, 16, 21, 42);
final _t2 = DateTime(2026, 8, 15, 13, 5);
final _t3 = DateTime(2026, 8, 14, 9, 30);

const demoStations = <Station>[
  Station(
    id: 'ST-001',
    name: 'Engineering Station',
    status: StationStatus.online,
    availability: 'Available',
  ),
  Station(
    id: 'ST-002',
    name: 'Library Station',
    status: StationStatus.online,
    availability: 'Almost Full',
  ),
  Station(
    id: 'ST-003',
    name: 'Science Station',
    status: StationStatus.offline,
    availability: 'Unavailable',
  ),
];

/// Campus collection points (Schedule Collection). Campus locations only —
/// no residential/home addresses.
const collectionPoints = <String>[
  'Engineering Building',
  'Library',
  'Main Gate',
  'Sports Hall',
  'Science Building',
  'Central Depot',
];

const collectionQuantities = <String>[
  '5–10 kg',
  '10–20 kg',
  '20–50 kg',
  '50+ kg',
];

const collectionWindows = <String>[
  '9:00 – 11:00 AM',
  '12:00 – 2:00 PM',
  '2:00 – 4:00 PM',
];

/// Next three days as schedule choices — always valid future dates.
List<String> upcomingCollectionDates({DateTime? now}) {
  final at = now ?? DateTime.now();
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  return [0, 1, 2]
      .map((i) => at.add(Duration(days: i)))
      .map((d) => '${d.day} ${months[d.month - 1]}')
      .toList();
}
