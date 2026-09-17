import 'package:flutter/material.dart' show IconData, Icons;

import '../models.dart';
import '../store.dart' show UserAccount;

/// Wire contract mappers between the SCWT Backend (FastAPI) backend
/// (snake_case JSON, `/api/v1`) and SCWT's domain models.
///
/// The backend is authoritative; these mappers never invent data — unknown /
/// not-yet-provided values stay zero/empty and the UI renders them as such.

String _displayCase(String key) =>
    key.isEmpty ? key : key[0].toUpperCase() + key.substring(1);

// ---------------------------------------------------------------------------
// Auth / user
// ---------------------------------------------------------------------------

/// `{token, user}` from POST /auth/login — or `{user}` from
/// GET /auth/me paired with the already-stored token.
class BackendSession {
  const BackendSession({required this.token, required this.user});
  final String token;
  final UserAccount user;
}

UserAccount userFromWire(Map<String, dynamic> j, {String? fallbackEmail}) {
  return UserAccount(
    name: (j['name'] as String?)?.trim().isNotEmpty == true
        ? j['name'] as String
        : 'SCWT Student',
    email: (j['email'] as String?) ?? fallbackEmail ?? '',
    studentId: (j['studentCode'] as String?) ?? '',
  );
}

int pointsFromWire(Map<String, dynamic> j) =>
    (j['points'] as num?)?.toInt() ?? 0;

// ---------------------------------------------------------------------------
// Stations
// ---------------------------------------------------------------------------

Station stationFromWire(Map<String, dynamic> j) {
  final status = (j['status'] as String? ?? 'offline').toLowerCase();
  final online = status == 'online';
  // User-facing availability only — raw mechanical states are not exposed.
  final availability = online ? 'Available' : 'Unavailable';
  return Station(
    id: (j['station_code'] as String?) ?? (j['id'] as String),
    name: (j['name'] as String?) ?? 'SCWT Station',
    status: online ? StationStatus.online : StationStatus.offline,
    availability: availability,
  );
}

List<Station> stationsFromWire(List<dynamic> items) =>
    items.map((e) => stationFromWire(e as Map<String, dynamic>)).toList();

// ---------------------------------------------------------------------------
// History → Contribution
// ---------------------------------------------------------------------------

Contribution contributionFromHistoryWire(Map<String, dynamic> j) {
  final cls = (j['predicted_class'] as String? ?? 'other');
  final weight = (j['weight_g'] as num?)?.toDouble() ?? 0;
  final confidence = (j['confidence'] as num?)?.toDouble();
  return Contribution(
    id: (j['operation_id'] as String?) ?? (j['id'] as String),
    materialType: _displayCase(cls),
    weight: weight,
    aiConfidence: confidence == null ? 0 : confidence * 100,
    targetBin: '${_displayCase(cls)} Bin',
    points: (j['points_awarded'] as num?)?.toInt() ?? 0,
    stationId: (j['station_id'] as String?) ?? '',
    timestamp:
        DateTime.tryParse((j['created_at'] as String?) ?? '') ?? DateTime.now(),
    verificationStatus: 'CONFIRMED',
  );
}

List<Contribution> contributionsFromHistoryWire(List<dynamic> items) => items
    .map((e) => contributionFromHistoryWire(e as Map<String, dynamic>))
    .toList();

// ---------------------------------------------------------------------------
// Deposit session wire (live + terminal)
// ---------------------------------------------------------------------------

/// Live deposit phases on the wire. `capture`/`analyzing` are the station-
/// camera phases; routing/moving/ready/detecting/measuring mirror physical
/// progress; the last four are terminal outcomes.
enum WireDepositStatus {
  capture('capture'),
  analyzing('analyzing'),
  pending('pending'),
  routing('routing'),
  moving('moving'),
  ready('ready'),
  detecting('detecting'),
  measuring('measuring'),
  confirmed('confirmed'),
  rejected('rejected'),
  cancelled('cancelled'),
  expired('expired');

  final String apiValue;
  const WireDepositStatus(this.apiValue);

  static WireDepositStatus tryFrom(String value) =>
      WireDepositStatus.values.firstWhere(
        (s) => s.apiValue == value,
        orElse: () => WireDepositStatus.pending,
      );

  bool get isTerminal =>
      this == confirmed ||
      this == rejected ||
      this == cancelled ||
      this == expired;

  /// Maps a backend phase onto the five verification-chain stages the
  /// Processing screen renders. Mechanical vocabulary stays behind the API.
  int get processingStage => switch (this) {
    capture => 0,
    analyzing => 1,
    routing || moving => 2,
    ready || detecting || measuring => 3,
    confirmed => 4,
    _ => 0,
  };
}

class WireDeposit {
  const WireDeposit({
    required this.operationId,
    required this.stationId,
    required this.status,
    required this.predictedClass,
    required this.confidence,
    required this.weightGrams,
    required this.pointsAwarded,
    required this.rejectReason,
  });

  final String operationId;
  final String stationId;
  final WireDepositStatus status;
  final String predictedClass; // '' until classified
  final double confidence; // 0 until classified
  final double weightGrams;
  final int pointsAwarded;
  final String? rejectReason;

  bool get isTerminal => status.isTerminal;

  static WireDeposit fromJson(Map<String, dynamic> j) => WireDeposit(
    operationId: j['operation_id'] as String,
    stationId: (j['station_id'] as String?) ?? '',
    status: WireDepositStatus.tryFrom((j['status'] as String?) ?? ''),
    predictedClass: (j['predicted_class'] as String?) ?? '',
    confidence: (j['confidence'] as num?)?.toDouble() ?? 0,
    weightGrams: (j['weight_g'] as num?)?.toDouble() ?? 0,
    pointsAwarded: (j['points_awarded'] as num?)?.toInt() ?? 0,
    rejectReason: j['reject_reason'] as String?,
  );

  /// Authoritative result as an SCWT [Contribution].
  Contribution toContribution({DateTime? at}) {
    final cls = predictedClass.isEmpty ? 'other' : predictedClass;
    return Contribution(
      id: operationId,
      materialType: _displayCase(cls),
      weight: weightGrams,
      aiConfidence: confidence * 100,
      targetBin: '${_displayCase(cls)} Bin',
      points: pointsAwarded,
      stationId: stationId,
      timestamp: at ?? DateTime.now(),
      verificationStatus: isTerminal && status == WireDepositStatus.confirmed
          ? 'CONFIRMED'
          : status.apiValue.toUpperCase(),
    );
  }
}

// ---------------------------------------------------------------------------
// Leaderboard
// ---------------------------------------------------------------------------

List<LeaderboardEntry> leaderboardFromWire(List<dynamic> items) {
  return List.generate(items.length, (i) {
    final j = items[i] as Map<String, dynamic>;
    // detail may carry recovered-kg text; extract when present.
    final detail = (j['detail'] as String?) ?? '';
    final kg =
        double.tryParse(
          RegExp(r'([\d.]+)').firstMatch(detail)?.group(1) ?? '',
        ) ??
        0;
    return LeaderboardEntry(
      facultyId: (j['id'] as String?) ?? '',
      facultyName: (j['name'] as String?) ?? '',
      rank: i + 1,
      points: (j['points'] as num?)?.toInt() ?? 0,
      weightKg: kg,
    );
  });
}

// ---------------------------------------------------------------------------
// Rewards catalog (production mode)
// ---------------------------------------------------------------------------

/// A redeemable reward as defined by the BACKEND catalog. The client never
/// invents rewards or costs in production — it displays these verbatim.
class BackendReward {
  const BackendReward({
    required this.id,
    required this.name,
    required this.provider,
    required this.description,
    required this.pointsCost,
    required this.valueLabel,
    required this.icon,
    required this.requiresDestination,
  });

  final String id;
  final String name;
  final String provider;
  final String description;
  final int pointsCost;
  final String valueLabel; // "10 EGP", "20% OFF", …
  final String icon; // Material icon name
  final bool requiresDestination; // cash payouts need a phone/handle

  static BackendReward fromJson(Map<String, dynamic> j) => BackendReward(
    id: j['id'] as String,
    name: (j['name'] as String?) ?? '',
    provider: (j['provider'] as String?) ?? '',
    description: (j['description'] as String?) ?? '',
    pointsCost: (j['points_cost'] as num?)?.toInt() ?? 0,
    valueLabel: (j['value_label'] as String?) ?? '',
    icon: (j['icon'] as String?) ?? 'card_giftcard',
    requiresDestination: j['requires_destination'] as bool? ?? false,
  );
}

List<BackendReward> rewardsFromWire(List<dynamic> items) => items
    .map((e) => BackendReward.fromJson(e as Map<String, dynamic>))
    .toList();

/// Maps the backend's icon-name strings to Material icons (safe fallback).
IconData rewardIcon(String name) => switch (name) {
  'account_balance_wallet' => Icons.account_balance_wallet,
  'card_giftcard' => Icons.card_giftcard,
  'local_cafe' || 'coffee' => Icons.local_cafe,
  'print' || 'print_outlined' => Icons.print,
  'percent' || 'discount' => Icons.percent,
  'inventory_2' => Icons.inventory_2,
  _ => Icons.redeem,
};
