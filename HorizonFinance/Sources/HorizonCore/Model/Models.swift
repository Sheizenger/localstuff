import Foundation

// MARK: - Базовые перечисления

/// Направление денег: пришло или ушло.
public enum MoneyFlow: String, Codable, CaseIterable, Hashable, Identifiable {
    case income
    case expense

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .income: return "Доход"
        case .expense: return "Расход"
        }
    }
}

/// Тип траты. Обязательные не считаются «красной зоной»,
/// свободные — это тот самый фонд «на всякое», который и надо держать в рамках.
public enum SpendKind: String, Codable, CaseIterable, Hashable, Identifiable {
    case essential
    case flexible

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .essential: return "Обязательные"
        case .flexible: return "Свободные"
        }
    }

    public var hint: String {
        switch self {
        case .essential: return "Аренда, счета, продукты, транспорт — то, что нельзя не заплатить"
        case .flexible: return "Кафе, покупки, поездки, подписки — то, что и съедает разницу"
        }
    }
}

/// Как считается темп накоплений, из которого строится прогноз по целям.
public enum PaceMode: String, Codable, CaseIterable, Hashable, Identifiable {
    case lastMonth
    case avg3
    case avg6
    case weighted
    case manual

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .lastMonth: return "Последний месяц"
        case .avg3: return "Среднее за 3 месяца"
        case .avg6: return "Среднее за 6 месяцев"
        case .weighted: return "Взвешенный (свежее — важнее)"
        case .manual: return "Задать вручную"
        }
    }

    public var shortTitle: String {
        switch self {
        case .lastMonth: return "по последнему месяцу"
        case .avg3: return "среднее за 3 мес."
        case .avg6: return "среднее за 6 мес."
        case .weighted: return "взвешенный темп"
        case .manual: return "заданный вручную"
        }
    }
}

/// Как распределять темп накоплений между целями.
public enum FundingMode: String, Codable, CaseIterable, Hashable, Identifiable {
    case priority
    case shares

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .priority: return "По очереди"
        case .shares: return "Параллельно, долями"
        }
    }

    public var hint: String {
        switch self {
        case .priority: return "Весь темп идёт в верхнюю цель, следующая стартует после её закрытия"
        case .shares: return "Каждая цель получает свою долю ежемесячного темпа"
        }
    }
}

// MARK: - Сущности

public struct Category: Identifiable, Codable, Hashable {
    public var id: UUID = UUID()
    public var name: String
    public var emoji: String = "•"
    public var flow: MoneyFlow = .expense
    public var kind: SpendKind = .flexible
    public var isArchived: Bool = false

    public var displayName: String { "\(emoji) \(name)" }

    public init(
        id: UUID = UUID(),
        name: String,
        emoji: String = "•",
        flow: MoneyFlow = .expense,
        kind: SpendKind = .flexible,
        isArchived: Bool = false
    ) {
        self.id = id
        self.name = name
        self.emoji = emoji
        self.flow = flow
        self.kind = kind
        self.isArchived = isArchived
    }
}

public struct Txn: Identifiable, Codable, Hashable {
    public var id: UUID = UUID()
    public var date: Date = Date()
    /// Всегда положительное число, знак определяется полем `flow`.
    public var amount: Double = 0
    public var flow: MoneyFlow = .expense
    public var categoryID: UUID? = nil
    public var note: String = ""

    /// Со знаком: доход «+», расход «−».
    public var signedAmount: Double { flow == .income ? amount : -amount }

    public init(
        id: UUID = UUID(),
        date: Date = Date(),
        amount: Double = 0,
        flow: MoneyFlow = .expense,
        categoryID: UUID? = nil,
        note: String = ""
    ) {
        self.id = id
        self.date = date
        self.amount = amount
        self.flow = flow
        self.categoryID = categoryID
        self.note = note
    }
}

/// Перевод денег в цель (или изъятие из неё, если сумма отрицательная).
public struct Contribution: Identifiable, Codable, Hashable {
    public var id: UUID = UUID()
    public var goalID: UUID
    public var date: Date = Date()
    public var amount: Double = 0
    public var note: String = ""

    public init(
        id: UUID = UUID(),
        goalID: UUID,
        date: Date = Date(),
        amount: Double = 0,
        note: String = ""
    ) {
        self.id = id
        self.goalID = goalID
        self.date = date
        self.amount = amount
        self.note = note
    }
}

public struct Goal: Identifiable, Codable, Hashable {
    public var id: UUID = UUID()
    public var title: String = ""
    public var emoji: String = "🎯"
    public var targetAmount: Double = 0
    /// Уже накоплено до начала учёта в приложении.
    public var startingAmount: Double = 0
    public var deadline: Date? = nil
    /// Меньше — важнее. Определяет очередь в режиме «по очереди».
    public var priority: Int = 0
    /// Доля месячного темпа (0...1) в режиме «параллельно, долями».
    public var share: Double = 0.5
    public var colorHex: String = "#4F8DF7"
    public var isArchived: Bool = false
    public var note: String = ""

    public init(
        id: UUID = UUID(),
        title: String = "",
        emoji: String = "🎯",
        targetAmount: Double = 0,
        startingAmount: Double = 0,
        deadline: Date? = nil,
        priority: Int = 0,
        share: Double = 0.5,
        colorHex: String = "#4F8DF7",
        isArchived: Bool = false,
        note: String = ""
    ) {
        self.id = id
        self.title = title
        self.emoji = emoji
        self.targetAmount = targetAmount
        self.startingAmount = startingAmount
        self.deadline = deadline
        self.priority = priority
        self.share = share
        self.colorHex = colorHex
        self.isArchived = isArchived
        self.note = note
    }
}

public struct Profile: Codable, Hashable {
    public var currencyCode: String = "EUR"
    /// Остаток на счетах на момент старта учёта (не считая того, что уже лежит в целях).
    public var openingBalance: Double = 0
    public var plannedIncome: Double = 0
    public var essentialsPlan: Double = 0
    /// Лимит свободных трат в месяц — база для «красной зоны».
    public var flexibleLimit: Double = 500
    /// План откладывать в месяц.
    public var savingsPlan: Double = 1000
    public var paceMode: PaceMode = .weighted
    public var manualPace: Double = 1500
    public var fundingMode: FundingMode = .priority

    public init(
        currencyCode: String = "EUR",
        openingBalance: Double = 0,
        plannedIncome: Double = 0,
        essentialsPlan: Double = 0,
        flexibleLimit: Double = 500,
        savingsPlan: Double = 1000,
        paceMode: PaceMode = .weighted,
        manualPace: Double = 1500,
        fundingMode: FundingMode = .priority
    ) {
        self.currencyCode = currencyCode
        self.openingBalance = openingBalance
        self.plannedIncome = plannedIncome
        self.essentialsPlan = essentialsPlan
        self.flexibleLimit = flexibleLimit
        self.savingsPlan = savingsPlan
        self.paceMode = paceMode
        self.manualPace = manualPace
        self.fundingMode = fundingMode
    }
}

public struct AppData: Codable {
    public var schemaVersion: Int = 1
    public var profile: Profile = Profile()
    public var categories: [Category] = []
    public var goals: [Goal] = []
    public var transactions: [Txn] = []
    public var contributions: [Contribution] = []

    public init(
        schemaVersion: Int = 1,
        profile: Profile = Profile(),
        categories: [Category] = [],
        goals: [Goal] = [],
        transactions: [Txn] = [],
        contributions: [Contribution] = []
    ) {
        self.schemaVersion = schemaVersion
        self.profile = profile
        self.categories = categories
        self.goals = goals
        self.transactions = transactions
        self.contributions = contributions
    }
}

// MARK: - Месяц как ключ

/// Год + месяц. Сравнимый, хешируемый, удобен как ось для графиков.
public struct MonthKey: Hashable, Comparable, Codable, Identifiable {
    public var year: Int
    public var month: Int

    public var id: Int { year * 100 + month }

    public init(year: Int, month: Int) {
        self.year = year
        self.month = month
    }

    public init(date: Date, calendar: Calendar = Cal.ru) {
        let parts = calendar.dateComponents([.year, .month], from: date)
        self.year = parts.year ?? 2000
        self.month = parts.month ?? 1
    }

    public static func < (lhs: MonthKey, rhs: MonthKey) -> Bool { lhs.id < rhs.id }

    /// Сквозной номер месяца — упрощает арифметику.
    public var index: Int { year * 12 + (month - 1) }

    public static func from(index: Int) -> MonthKey {
        let y = Int((Double(index) / 12.0).rounded(.down))
        let m = index - y * 12 + 1
        return MonthKey(year: y, month: m)
    }

    public func adding(_ months: Int) -> MonthKey { MonthKey.from(index: index + months) }

    public static func distance(from: MonthKey, to: MonthKey) -> Int { to.index - from.index }

    public var startDate: Date {
        var parts = DateComponents()
        parts.year = year
        parts.month = month
        parts.day = 1
        return Cal.ru.date(from: parts) ?? Date()
    }

    public var endDate: Date {
        Cal.ru.date(byAdding: DateComponents(month: 1, day: -1), to: startDate) ?? startDate
    }

    public var daysInMonth: Int {
        Cal.ru.range(of: .day, in: .month, for: startDate)?.count ?? 30
    }

    public static var current: MonthKey { MonthKey(date: Date()) }

    /// «сен 26» — для плотных подписей на оси графика.
    public var shortTitle: String { Fmt.monthShort.string(from: startDate) }

    /// «Сентябрь 2026» — для заголовков.
    public var fullTitle: String { Fmt.monthFull.string(from: startDate).capitalizedFirst }

    /// «сентябрь 2026» — для списков.
    public var listTitle: String { Fmt.monthFull.string(from: startDate) }
}

// MARK: - Календарь и форматтеры

public enum Cal {
    /// Один календарь на всё приложение: неделя с понедельника, русская локаль.
    public static let ru: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.locale = Locale(identifier: "ru_RU")
        c.firstWeekday = 2
        return c
    }()
}

public enum Fmt {
    public static let locale = Locale(identifier: "ru_RU")

    public static let monthShort: DateFormatter = {
        let f = DateFormatter()
        f.locale = locale
        f.calendar = Cal.ru
        f.dateFormat = "LLL yy"
        return f
    }()

    public static let monthFull: DateFormatter = {
        let f = DateFormatter()
        f.locale = locale
        f.calendar = Cal.ru
        f.dateFormat = "LLLL yyyy"
        return f
    }()

    public static let dayLong: DateFormatter = {
        let f = DateFormatter()
        f.locale = locale
        f.calendar = Cal.ru
        f.dateFormat = "d MMMM, EEEE"
        return f
    }()

    public static let dayShort: DateFormatter = {
        let f = DateFormatter()
        f.locale = locale
        f.calendar = Cal.ru
        f.dateFormat = "d MMM yyyy"
        return f
    }()

    /// Форматтеры дорогие, а суммы рисуются сотнями за один проход — держим их в кэше.
    private static var moneyFormatters: [String: NumberFormatter] = [:]

    private static func moneyFormatter(code: String, fraction: Bool) -> NumberFormatter {
        let key = "\(code)-\(fraction)"
        if let cached = moneyFormatters[key] { return cached }
        let f = NumberFormatter()
        f.locale = locale
        f.numberStyle = .currency
        f.currencyCode = code
        f.currencySymbol = symbol(for: code)
        f.maximumFractionDigits = fraction ? 2 : 0
        f.minimumFractionDigits = 0
        moneyFormatters[key] = f
        return f
    }

    public static func money(_ value: Double, code: String, fraction: Bool = false) -> String {
        let safe = value.isFinite ? value : 0
        let f = moneyFormatter(code: code, fraction: fraction)
        return f.string(from: NSNumber(value: safe)) ?? "\(Int(safe))"
    }

    public static func signedMoney(_ value: Double, code: String, fraction: Bool = false) -> String {
        let body = money(abs(value), code: code, fraction: fraction)
        if value > 0 { return "+" + body }
        if value < 0 { return "−" + body }
        return body
    }

    public static func symbol(for code: String) -> String {
        switch code.uppercased() {
        case "EUR": return "€"
        case "USD": return "$"
        case "RUB": return "₽"
        case "GBP": return "£"
        case "PLN": return "zł"
        case "RSD": return "дин."
        case "TRY": return "₺"
        case "GEL": return "₾"
        default: return code.uppercased()
        }
    }

    public static func percent(_ value: Double, digits: Int = 0) -> String {
        let safe = value.isFinite ? value : 0
        return String(format: "%.\(digits)f%%", safe * 100)
    }

    /// «3 месяца», «1 месяц», «7 месяцев» — с правильным окончанием.
    public static func monthsWord(_ count: Int) -> String {
        let n = abs(count) % 100
        let n1 = n % 10
        if n > 10 && n < 20 { return "\(count) месяцев" }
        if n1 == 1 { return "\(count) месяц" }
        if n1 >= 2 && n1 <= 4 { return "\(count) месяца" }
        return "\(count) месяцев"
    }

    public static func daysWord(_ count: Int) -> String {
        let n = abs(count) % 100
        let n1 = n % 10
        if n > 10 && n < 20 { return "\(count) дней" }
        if n1 == 1 { return "\(count) день" }
        if n1 >= 2 && n1 <= 4 { return "\(count) дня" }
        return "\(count) дней"
    }

    /// Человекочитаемый срок: «4 месяца», «1 год 3 месяца», «больше 15 лет».
    public static func horizon(months: Double) -> String {
        if !months.isFinite || months < 0 { return "—" }
        if months < 0.5 { return "меньше месяца" }
        let total = Int(months.rounded())
        if total > 180 { return "больше 15 лет" }
        if total < 12 { return monthsWord(total) }
        let years = total / 12
        let rest = total % 12
        let yearsWord: String
        let y1 = years % 10
        let y100 = years % 100
        if y100 > 10 && y100 < 20 { yearsWord = "\(years) лет" }
        else if y1 == 1 { yearsWord = "\(years) год" }
        else if y1 >= 2 && y1 <= 4 { yearsWord = "\(years) года" }
        else { yearsWord = "\(years) лет" }
        if rest == 0 { return yearsWord }
        return yearsWord + " " + monthsWord(rest)
    }
}

extension String {
    public var capitalizedFirst: String {
        guard let first = self.first else { return self }
        return String(first).uppercased() + self.dropFirst()
    }
}

extension Double {
    /// Защита от NaN/бесконечностей, которые ломают вёрстку и графики.
    public var finiteOrZero: Double { isFinite ? self : 0 }

    public func clamped(_ lower: Double, _ upper: Double) -> Double {
        Swift.min(Swift.max(self, lower), upper)
    }
}
