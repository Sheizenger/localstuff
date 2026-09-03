import Foundation

// MARK: - Агрегаты по месяцам

struct MonthStats: Identifiable, Hashable {
    var month: MonthKey
    var income: Double = 0
    var essential: Double = 0
    var flexible: Double = 0
    /// Сколько за месяц переведено в цели (справочно, на темп не влияет).
    var moved: Double = 0

    var id: Int { month.id }
    var expense: Double { essential + flexible }
    /// То, что реально осталось за месяц — база для темпа накоплений.
    var net: Double { income - expense }
    var savingsRate: Double { income > 0 ? net / income : 0 }
    var hasData: Bool { income != 0 || expense != 0 || moved != 0 }
}

// MARK: - Зоны и статус бюджета

enum Zone: String {
    case safe
    case warning
    case danger

    var title: String {
        switch self {
        case .safe: return "Зелёная зона"
        case .warning: return "Жёлтая зона"
        case .danger: return "Красная зона"
        }
    }
}

struct BudgetStatus {
    var limit: Double
    var spent: Double
    var remaining: Double
    var projected: Double
    var monthProgress: Double
    var daysLeft: Int
    var dailyAllowance: Double
    var zone: Zone
    var headline: String
    var advice: String

    var usedShare: Double {
        guard limit > 0 else { return spent > 0 ? 1 : 0 }
        return (spent / limit).clamped(0, 1.5)
    }
}

// MARK: - Аналитика

/// Все производные числа считаются здесь, из «сырых» данных.
/// `today` вынесен параметром, чтобы поведение было воспроизводимым.
struct Analytics {
    let data: AppData
    let today: Date

    init(data: AppData, today: Date = Date()) {
        self.data = data
        self.today = today
    }

    var profile: Profile { data.profile }
    var currency: String { data.profile.currencyCode }
    var currentMonth: MonthKey { MonthKey(date: today) }

    var categoryByID: [UUID: Category] {
        var map: [UUID: Category] = [:]
        for c in data.categories { map[c.id] = c }
        return map
    }

    func category(for txn: Txn) -> Category? {
        guard let id = txn.categoryID else { return nil }
        return categoryByID[id]
    }

    func kind(of txn: Txn) -> SpendKind {
        category(for: txn)?.kind ?? .flexible
    }

    var activeGoals: [Goal] {
        data.goals.filter { !$0.isArchived }.sorted { lhs, rhs in
            if lhs.priority != rhs.priority { return lhs.priority < rhs.priority }
            return lhs.title.localizedCaseInsensitiveCompare(rhs.title) == .orderedAscending
        }
    }

    // MARK: Помесячная статистика

    /// Непрерывный ряд месяцев от самой ранней операции (но не короче 12 месяцев) до текущего.
    var monthlyStats: [MonthStats] {
        var buckets: [Int: MonthStats] = [:]

        func bucket(_ key: MonthKey) -> MonthStats {
            buckets[key.id] ?? MonthStats(month: key)
        }

        for t in data.transactions {
            let key = MonthKey(date: t.date)
            var b = bucket(key)
            if t.flow == .income {
                b.income += t.amount
            } else if kind(of: t) == .essential {
                b.essential += t.amount
            } else {
                b.flexible += t.amount
            }
            buckets[key.id] = b
        }

        for c in data.contributions {
            let key = MonthKey(date: c.date)
            var b = bucket(key)
            b.moved += c.amount
            buckets[key.id] = b
        }

        let now = currentMonth
        var earliest = now.adding(-11)
        for t in data.transactions {
            let k = MonthKey(date: t.date)
            if k < earliest { earliest = k }
        }
        for c in data.contributions {
            let k = MonthKey(date: c.date)
            if k < earliest { earliest = k }
        }

        // Ограничиваем историю пятью годами, чтобы график оставался читаемым.
        if MonthKey.distance(from: earliest, to: now) > 60 {
            earliest = now.adding(-60)
        }

        var result: [MonthStats] = []
        var cursor = earliest
        while cursor <= now {
            result.append(buckets[cursor.id] ?? MonthStats(month: cursor))
            cursor = cursor.adding(1)
        }
        return result
    }

    /// Только завершённые месяцы — текущий ещё не показателен.
    var completedMonths: [MonthStats] {
        let now = currentMonth
        return monthlyStats.filter { $0.month < now }
    }

    func stats(for month: MonthKey) -> MonthStats {
        monthlyStats.first(where: { $0.month == month }) ?? MonthStats(month: month)
    }

    var thisMonth: MonthStats { stats(for: currentMonth) }

    func lastStats(_ count: Int) -> [MonthStats] {
        let all = monthlyStats
        guard all.count > count else { return all }
        return Array(all.suffix(count))
    }

    // MARK: Темп накоплений

    struct PaceInfo {
        var value: Double
        var basis: String
        var monthsUsed: Int
        /// true — реальных данных не хватило, взят план из настроек.
        var isPlanned: Bool
    }

    var pace: PaceInfo {
        let mode = profile.paceMode
        if mode == .manual {
            return PaceInfo(value: profile.manualPace, basis: "задан вручную", monthsUsed: 0, isPlanned: false)
        }

        // Считаем только по месяцам, где вообще были движения.
        let history = completedMonths.filter { $0.hasData }
        if history.isEmpty {
            return PaceInfo(value: plannedPace, basis: "план из настроек", monthsUsed: 0, isPlanned: true)
        }

        switch mode {
        case .lastMonth:
            let last = history.suffix(1)
            return PaceInfo(value: average(last), basis: PaceMode.lastMonth.shortTitle, monthsUsed: last.count, isPlanned: false)
        case .avg3:
            let window = history.suffix(3)
            return PaceInfo(value: average(window), basis: PaceMode.avg3.shortTitle, monthsUsed: window.count, isPlanned: false)
        case .avg6:
            let window = history.suffix(6)
            return PaceInfo(value: average(window), basis: PaceMode.avg6.shortTitle, monthsUsed: window.count, isPlanned: false)
        case .weighted:
            let window = Array(history.suffix(3))
            let weights: [Double] = [1, 2, 3]
            let used = Array(weights.suffix(window.count))
            let sumW = used.reduce(0, +)
            guard sumW > 0 else {
                return PaceInfo(value: plannedPace, basis: "план из настроек", monthsUsed: 0, isPlanned: true)
            }
            var acc = 0.0
            for (i, m) in window.enumerated() { acc += m.net * used[i] }
            return PaceInfo(value: acc / sumW, basis: PaceMode.weighted.shortTitle, monthsUsed: window.count, isPlanned: false)
        case .manual:
            return PaceInfo(value: profile.manualPace, basis: "задан вручную", monthsUsed: 0, isPlanned: false)
        }
    }

    /// Плановый темп из настроек — запасной вариант, пока нет истории.
    var plannedPace: Double {
        let byPlan = profile.plannedIncome - profile.essentialsPlan - profile.flexibleLimit
        if byPlan > 0 { return byPlan }
        return max(profile.savingsPlan, 0)
    }

    private func average<S: Sequence>(_ months: S) -> Double where S.Element == MonthStats {
        let list = Array(months)
        guard !list.isEmpty else { return 0 }
        return list.reduce(0.0) { $0 + $1.net } / Double(list.count)
    }

    // MARK: Деньги

    /// Сколько уже лежит в конкретной цели.
    func saved(for goal: Goal) -> Double {
        let moved = data.contributions.filter { $0.goalID == goal.id }.reduce(0.0) { $0 + $1.amount }
        return goal.startingAmount + moved
    }

    var totalInGoals: Double {
        data.goals.filter { !$0.isArchived }.reduce(0.0) { $0 + saved(for: $1) }
    }

    /// Средний фактический расход в месяц по набору категорий — по завершённым месяцам с данными.
    func averageMonthlySpend(categoryIDs: Set<UUID>, months: Int = 3) -> Double {
        let window = completedMonths.filter { $0.hasData }.suffix(months).map { $0.month.id }
        guard !window.isEmpty else { return 0 }
        let keys = Set(window)

        var sum = 0.0
        for txn in data.transactions where txn.flow == .expense {
            guard let id = txn.categoryID, categoryIDs.contains(id) else { continue }
            if keys.contains(MonthKey(date: txn.date).id) { sum += txn.amount }
        }
        return sum / Double(window.count)
    }

    /// Идентификаторы категорий по названиям — чтобы связать корзину с фактическими тратами.
    func categoryIDs(named names: [String]) -> Set<UUID> {
        let lowered = Set(names.map { $0.lowercased() })
        return Set(data.categories.filter { lowered.contains($0.name.lowercased()) }.map { $0.id })
    }

    /// Свободные деньги: всё, что не разложено по целям.
    var freeCash: Double {
        let flows = data.transactions.reduce(0.0) { $0 + $1.signedAmount }
        let moved = data.contributions.reduce(0.0) { $0 + $1.amount }
        return profile.openingBalance + flows - moved
    }

    /// Общий капитал: свободные деньги плюс всё, что в целях.
    var totalCapital: Double { freeCash + totalInGoals }

    /// Средние обязательные расходы в месяц — база для «на сколько месяцев хватит».
    var averageEssentials: Double {
        let history = completedMonths.filter { $0.hasData }.suffix(6)
        if history.isEmpty { return max(profile.essentialsPlan, 0) }
        let sum = history.reduce(0.0) { $0 + $1.essential }
        return sum / Double(history.count)
    }

    var averageBurn: Double {
        let history = completedMonths.filter { $0.hasData }.suffix(6)
        if history.isEmpty { return max(profile.essentialsPlan + profile.flexibleLimit, 0) }
        let sum = history.reduce(0.0) { $0 + $1.expense }
        return sum / Double(history.count)
    }

    /// На сколько месяцев жизни хватит всех накоплений при текущих тратах.
    var runwayMonths: Double {
        let burn = averageBurn
        guard burn > 0 else { return 0 }
        return max(totalCapital, 0) / burn
    }

    // MARK: Красная зона текущего месяца

    var budgetStatus: BudgetStatus {
        let month = currentMonth
        let limit = max(profile.flexibleLimit, 0)
        let spent = thisMonth.flexible
        let remaining = limit - spent

        let days = Double(month.daysInMonth)
        let dayNow = Double(Cal.ru.component(.day, from: today))
        let progress = (dayNow / days).clamped(0.02, 1)
        let daysLeft = max(month.daysInMonth - Int(dayNow) + 1, 0)
        let projected = progress > 0 ? spent / progress : spent
        let dailyAllowance = daysLeft > 0 ? max(remaining, 0) / Double(daysLeft) : max(remaining, 0)

        var zone: Zone = .safe
        if limit <= 0 {
            zone = spent > 0 ? .warning : .safe
        } else if spent >= limit {
            zone = .danger
        } else if remaining / limit <= 0.15 {
            zone = .danger
        } else if projected > limit * 1.05 || remaining / limit <= 0.35 {
            zone = .warning
        }

        let headline: String
        let advice: String
        let cur = currency

        switch zone {
        case .safe:
            headline = "Запас в порядке"
            advice = "До конца месяца можно тратить примерно \(Fmt.money(dailyAllowance, code: cur)) в день — темп накоплений это не сломает."
        case .warning:
            if projected > limit * 1.05 {
                headline = "Идёте с опережением лимита"
                advice = "При таком темпе к концу месяца выйдет около \(Fmt.money(projected, code: cur)) вместо \(Fmt.money(limit, code: cur)). Держите \(Fmt.money(dailyAllowance, code: cur)) в день — и всё сойдётся."
            } else {
                headline = "Запас тает"
                advice = "Осталось \(Fmt.money(max(remaining, 0), code: cur)) на \(Fmt.daysWord(daysLeft)). Крупные покупки лучше перенести на следующий месяц."
            }
        case .danger:
            if spent >= limit && limit > 0 {
                headline = "Лимит свободных трат исчерпан"
                advice = "Перерасход \(Fmt.money(spent - limit, code: cur)). Это не повод лезть в накопления — покупка переносится на следующий месяц."
            } else {
                headline = "Красная зона"
                advice = "Осталось всего \(Fmt.money(max(remaining, 0), code: cur)) на \(Fmt.daysWord(daysLeft)). Дальше каждая трата съедает темп накоплений."
            }
        }

        return BudgetStatus(
            limit: limit,
            spent: spent,
            remaining: remaining,
            projected: projected,
            monthProgress: progress,
            daysLeft: daysLeft,
            dailyAllowance: dailyAllowance,
            zone: zone,
            headline: headline,
            advice: advice
        )
    }

    // MARK: Капитал во времени

    struct CapitalPoint: Identifiable, Hashable {
        var month: MonthKey
        var value: Double
        var isForecast: Bool
        var id: Int { month.id }
    }

    /// Фактическая кривая капитала по месяцам.
    func capitalHistory(months: Int = 12) -> [CapitalPoint] {
        let all = monthlyStats
        guard !all.isEmpty else { return [] }

        let base = profile.openingBalance + data.goals.reduce(0.0) { $0 + $1.startingAmount }
        var running = base
        var points: [CapitalPoint] = []
        for m in all {
            running += m.net
            points.append(CapitalPoint(month: m.month, value: running, isForecast: false))
        }
        if points.count > months { points = Array(points.suffix(months)) }
        return points
    }

    /// Продолжение кривой вперёд по текущему темпу. Начинается с последней фактической точки,
    /// чтобы линия прогноза стыковалась с фактом без разрыва.
    func capitalForecast(months: Int = 12) -> [CapitalPoint] {
        let history = capitalHistory(months: 1)
        let startValue = history.last?.value ?? totalCapital
        let startMonth = history.last?.month ?? currentMonth
        let step = pace.value

        var points: [CapitalPoint] = [CapitalPoint(month: startMonth, value: startValue, isForecast: true)]
        var value = startValue
        for i in 1...max(months, 1) {
            value += step
            points.append(CapitalPoint(month: startMonth.adding(i), value: value, isForecast: true))
        }
        return points
    }

    // MARK: Категории

    struct CategorySlice: Identifiable, Hashable {
        var categoryID: UUID?
        var name: String
        var emoji: String
        var kind: SpendKind
        var amount: Double
        var share: Double
        var id: String { categoryID?.uuidString ?? "none" }
    }

    /// Разбивка расходов месяца по категориям, от большего к меньшему.
    func expenseBreakdown(month: MonthKey) -> [CategorySlice] {
        let txns = data.transactions.filter { $0.flow == .expense && MonthKey(date: $0.date) == month }
        guard !txns.isEmpty else { return [] }

        var sums: [String: CategorySlice] = [:]
        for t in txns {
            let cat = category(for: t)
            let key = cat?.id.uuidString ?? "none"
            var slice = sums[key] ?? CategorySlice(
                categoryID: cat?.id,
                name: cat?.name ?? "Без категории",
                emoji: cat?.emoji ?? "•",
                kind: cat?.kind ?? .flexible,
                amount: 0,
                share: 0
            )
            slice.amount += t.amount
            sums[key] = slice
        }

        let total = sums.values.reduce(0.0) { $0 + $1.amount }
        return sums.values
            .map { slice -> CategorySlice in
                var s = slice
                s.share = total > 0 ? s.amount / total : 0
                return s
            }
            .sorted { $0.amount > $1.amount }
    }
}
