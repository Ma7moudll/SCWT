// Backend-ready data models for SCWT.
//
// Each model exposes toJson/fromJson so a real FastAPI backend can be
// connected later without changing the UI layer.

class Contribution {
  final String id;
  final String materialType;
  final double weight; // grams
  final double aiConfidence; // 0-100
  final String targetBin;
  final int points;
  final String stationId;
  final DateTime timestamp;
  final String verificationStatus;

  const Contribution({
    required this.id,
    required this.materialType,
    required this.weight,
    required this.aiConfidence,
    required this.targetBin,
    required this.points,
    required this.stationId,
    required this.timestamp,
    this.verificationStatus = 'verified',
  });

  Contribution copyWith({String? id, DateTime? timestamp}) => Contribution(
    id: id ?? this.id,
    materialType: materialType,
    weight: weight,
    aiConfidence: aiConfidence,
    targetBin: targetBin,
    points: points,
    stationId: stationId,
    timestamp: timestamp ?? this.timestamp,
    verificationStatus: verificationStatus,
  );

  Map<String, Object?> toJson() => {
    'id': id,
    'materialType': materialType,
    'weight': weight,
    'aiConfidence': aiConfidence,
    'targetBin': targetBin,
    'points': points,
    'stationId': stationId,
    'timestamp': timestamp.toIso8601String(),
    'verificationStatus': verificationStatus,
  };

  factory Contribution.fromJson(Map<String, Object?> j) => Contribution(
    id: j['id'] as String,
    materialType: j['materialType'] as String,
    weight: (j['weight'] as num).toDouble(),
    aiConfidence: (j['aiConfidence'] as num).toDouble(),
    targetBin: j['targetBin'] as String,
    points: j['points'] as int,
    stationId: j['stationId'] as String,
    timestamp: DateTime.parse(j['timestamp'] as String),
    verificationStatus: (j['verificationStatus'] as String?) ?? 'verified',
  );

  /// Formatted, e.g. "18.4 g".
  String get weightDisplay => '${weight.toStringAsFixed(1)} g';

  String get dateDisplay {
    const months = [
      'January',
      'February',
      'March',
      'April',
      'May',
      'June',
      'July',
      'August',
      'September',
      'October',
      'November',
      'December',
    ];
    return '${timestamp.day} ${months[timestamp.month - 1]} ${timestamp.year}';
  }

  String get timeDisplay {
    final h = timestamp.hour;
    final m = timestamp.minute.toString().padLeft(2, '0');
    final period = h >= 12 ? 'PM' : 'AM';
    final hour12 = (h % 12 == 0) ? 12 : h % 12;
    return '${hour12.toString().padLeft(2, '0')}:$m $period';
  }
}

/// A single row in the faculty leaderboard.
class LeaderboardEntry {
  final String facultyId;
  final String facultyName;
  final int rank;
  final int points;
  final double weightKg;

  const LeaderboardEntry({
    required this.facultyId,
    required this.facultyName,
    required this.rank,
    required this.points,
    required this.weightKg,
  });

  Map<String, Object?> toJson() => {
    'facultyId': facultyId,
    'facultyName': facultyName,
    'rank': rank,
    'points': points,
    'weightKg': weightKg,
  };

  factory LeaderboardEntry.fromJson(Map<String, Object?> j) => LeaderboardEntry(
    facultyId: j['facultyId'] as String,
    facultyName: j['facultyName'] as String,
    rank: j['rank'] as int,
    points: j['points'] as int,
    weightKg: (j['weightKg'] as num).toDouble(),
  );
}

class Faculty {
  final String id;
  final String name;
  final int rank;
  final int points;
  final double weightKg;
  final int students;
  final List<Contribution> recentContributions;
  final double weeklyProgress; // 0-1

  const Faculty({
    required this.id,
    required this.name,
    required this.rank,
    required this.points,
    required this.weightKg,
    required this.students,
    required this.recentContributions,
    required this.weeklyProgress,
  });

  Map<String, Object?> toJson() => {
    'id': id,
    'name': name,
    'rank': rank,
    'points': points,
    'weightKg': weightKg,
    'students': students,
    'weeklyProgress': weeklyProgress,
    'recentContributions': recentContributions.map((c) => c.toJson()).toList(),
  };

  factory Faculty.fromJson(Map<String, Object?> j) => Faculty(
    id: j['id'] as String,
    name: j['name'] as String,
    rank: j['rank'] as int,
    points: j['points'] as int,
    weightKg: (j['weightKg'] as num).toDouble(),
    students: j['students'] as int,
    weeklyProgress: (j['weeklyProgress'] as num).toDouble(),
    recentContributions: (j['recentContributions'] as List)
        .map((e) => Contribution.fromJson(e as Map<String, Object?>))
        .toList(),
  );
}

class Station {
  final String id;
  final String name;
  final StationStatus status;
  final String availability; // e.g. "Available", "Almost Full"

  const Station({
    required this.id,
    required this.name,
    required this.status,
    required this.availability,
  });

  Map<String, Object?> toJson() => {
    'id': id,
    'name': name,
    'status': status.name,
    'availability': availability,
  };

  factory Station.fromJson(Map<String, Object?> j) => Station(
    id: j['id'] as String,
    name: j['name'] as String,
    status: StationStatus.values.firstWhere((e) => e.name == j['status']),
    availability: j['availability'] as String,
  );
}

enum StationStatus { online, offline }

class AppNotification {
  final String id;
  final String title;
  final String body;
  final String time;
  final bool read;
  final String iconKey; // maps to an IconData in the UI layer

  const AppNotification({
    required this.id,
    required this.title,
    required this.body,
    required this.time,
    required this.iconKey,
    this.read = false,
  });

  AppNotification markRead() => AppNotification(
    id: id,
    title: title,
    body: body,
    time: time,
    iconKey: iconKey,
    read: true,
  );

  Map<String, Object?> toJson() => {
    'id': id,
    'title': title,
    'body': body,
    'time': time,
    'read': read,
    'iconKey': iconKey,
  };

  factory AppNotification.fromJson(Map<String, Object?> j) => AppNotification(
    id: j['id'] as String,
    title: j['title'] as String,
    body: j['body'] as String,
    time: j['time'] as String,
    read: j['read'] as bool? ?? false,
    iconKey: j['iconKey'] as String? ?? 'eco',
  );
}

// ---------------------------------------------------------------------------
// Material configuration (final MVP set)
// ---------------------------------------------------------------------------

/// The only material categories allowed in the Student App.
const List<String> validMaterialTypes = ['plastic', 'metal', 'paper', 'other'];

const Map<String, int> _materialPoints = {
  'plastic': 10,
  'metal': 15,
  'paper': 8,
  'other': 5,
};

/// Final MVP points awarded per verified material. Unknown materials fall
/// back to the "other" value. Points are awarded ONLY after successful
/// physical verification, never for scanning alone.
int pointsForMaterial(String materialType) {
  final key = materialType.trim().toLowerCase();
  return _materialPoints[key] ?? _materialPoints['other']!;
}

// ---------------------------------------------------------------------------
// Recycling session (maps to POST /deposit/session)
// ---------------------------------------------------------------------------

/// Lifecycle of a single recycling session (maps to POST /deposit/session).
/// The Smart Bin TABLET is the device that scans the student's Dynamic QR —
/// the Student App only displays it and waits for identification.
enum SessionStatus {
  /// No active journey.
  idle,

  /// A station has been picked; the student is about to present their QR.
  stationSelected,

  /// The student's Dynamic QR is displayed, waiting for the tablet to scan it.
  waitingForStudentIdentification,

  /// The tablet identified the student for this session.
  studentIdentified,

  /// Identification complete — the student may place waste.
  readyForDeposit,

  /// The deposit is being processed (camera/AI/sorting).
  processing,

  /// IR + load cell verification in progress.
  verifying,

  /// Deposit verified (DROP_CONFIRMED + WEIGHT_VERIFIED) and points awarded.
  completed,

  failed,
  expired,
}

class RecyclingSession {
  final String sessionId;
  final String studentId;
  final String stationId;
  final DateTime startedAt;
  final DateTime expiresAt;
  final SessionStatus status;

  const RecyclingSession({
    required this.sessionId,
    required this.studentId,
    required this.stationId,
    required this.startedAt,
    required this.expiresAt,
    required this.status,
  });

  RecyclingSession copyWith({String? stationId, SessionStatus? status}) =>
      RecyclingSession(
        sessionId: sessionId,
        studentId: studentId,
        stationId: stationId ?? this.stationId,
        startedAt: startedAt,
        expiresAt: expiresAt,
        status: status ?? this.status,
      );

  Map<String, Object?> toJson() => {
    'sessionId': sessionId,
    'studentId': studentId,
    'stationId': stationId,
    'startedAt': startedAt.toIso8601String(),
    'expiresAt': expiresAt.toIso8601String(),
    'status': status.name,
  };

  factory RecyclingSession.fromJson(Map<String, Object?> j) => RecyclingSession(
    sessionId: j['sessionId'] as String,
    studentId: j['studentId'] as String,
    stationId: j['stationId'] as String,
    startedAt: DateTime.parse(j['startedAt'] as String),
    expiresAt: DateTime.parse(j['expiresAt'] as String),
    status: SessionStatus.values.firstWhere((e) => e.name == j['status']),
  );
}

// ---------------------------------------------------------------------------
// Schedule Collection (bulk campus material, NOT individual Smart Bin drops)
// ---------------------------------------------------------------------------

/// Lifecycle of a campus collection request. For the MVP the status is always
/// [CollectionStatus.pending]; the backend/admin approves and advances it.
enum CollectionStatus {
  pending,
  approved,
  scheduled,
  collecting,
  collected,
  verified,
  cancelled,
}

class CollectionRequest {
  final String id;
  final String materialType;
  final String estimatedQuantity; // e.g. "5–10 kg"
  final String collectionPoint; // campus location
  final String preferredDate;
  final String timeWindow;
  final CollectionStatus status;
  final DateTime requestedAt;

  const CollectionRequest({
    required this.id,
    required this.materialType,
    required this.estimatedQuantity,
    required this.collectionPoint,
    required this.preferredDate,
    required this.timeWindow,
    this.status = CollectionStatus.pending,
    required this.requestedAt,
  });

  CollectionRequest copyWith({CollectionStatus? status}) => CollectionRequest(
    id: id,
    materialType: materialType,
    estimatedQuantity: estimatedQuantity,
    collectionPoint: collectionPoint,
    preferredDate: preferredDate,
    timeWindow: timeWindow,
    status: status ?? this.status,
    requestedAt: requestedAt,
  );

  Map<String, Object?> toJson() => {
    'id': id,
    'materialType': materialType,
    'estimatedQuantity': estimatedQuantity,
    'collectionPoint': collectionPoint,
    'preferredDate': preferredDate,
    'timeWindow': timeWindow,
    'status': status.name,
    'requestedAt': requestedAt.toIso8601String(),
  };

  factory CollectionRequest.fromJson(Map<String, Object?> j) =>
      CollectionRequest(
        id: j['id'] as String,
        materialType: j['materialType'] as String,
        estimatedQuantity: j['estimatedQuantity'] as String,
        collectionPoint: j['collectionPoint'] as String,
        preferredDate: j['preferredDate'] as String,
        timeWindow: j['timeWindow'] as String,
        status: CollectionStatus.values.firstWhere(
          (e) => e.name == j['status'],
        ),
        requestedAt: DateTime.parse(j['requestedAt'] as String),
      );

  String get statusLabel => switch (status) {
    CollectionStatus.pending => 'Pending',
    CollectionStatus.approved => 'Approved',
    CollectionStatus.scheduled => 'Scheduled',
    CollectionStatus.collecting => 'Collecting',
    CollectionStatus.collected => 'Collected',
    CollectionStatus.verified => 'Verified',
    CollectionStatus.cancelled => 'Cancelled',
  };
}
