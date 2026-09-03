import Foundation

// MARK: - Базовые перечисления

/// Направление денег: пришло или ушло.
enum MoneyFlow: String, Codable, CaseIterable, Hashable, Identifiable {
    case income
    case expense

    var id: String { rawValue }

    var title: String {
        switch self {
        case .income: return "Доход"
        case .expense: return "Расход"
        }
    }
}

/// Тип траты. Обязательные не считаются «красной зоной»,
/// свободные — это тот самый фонд «на всякое», который и надо держать в рамках.
enum SpendKind: String, Codable, CaseIterable, Hashable, Identifiable {
    case essential
    case flexible

    var id: String { rawValue }

    var title: String {
        switch self {
        case .essential: return "Обязательные"
        case .flexible: return "Свободные"
        }
    }

    var hint: String {
        switch self {
        case .essential: return "Аренда, счета, продукты, транспорт — то, что нельзя не заплатить"
        case .flexible: return "Кафе, покупки, поездки, подписки — то, что и съедает разницу"
        }
    }
}

/// Как считается темп накоплений, из которого строится прогноз по целям.
enum PaceMode: String, Codable, CaseIterable, Hashable, Identifiable {
    case lastMonth
    case avg3
    case avg6
    case weighted
    case manual

    var id: String { rawValue }

    var title: String {
        switch self {
        case .lastMonth: return "Последний месяц"
        case .avg3: return "Среднее за 3 месяца"
        case .avg6: return "Среднее за 6 месяцев"
        case .weighted: return "Взвешенный (свежее — важнее)"
        case .manual: return "Задать вручную"
        }
    }

    var shortTitle: String {
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
enum FundingMode: String, Codable, CaseIterable, Hashable, Identifiable {
    case priority
    case shares

    var id: String { rawValue }

    var title: String {
        switch self {
        case .priority: return "По очереди"
        case .shares: return "Параллельно, долями"
        }
    }

    var hint: String {
        switch self {
        case .priority: return "Весь темп идёт в верхнюю цель, следующая стартует после её закрытия"
        case .shares: return "Каждая цель получает свою долю ежемесячного темпа"
        }
    }
}

// MARK: - Сущности

struct Category: Identifiable, Codable, Hashable {
    var id: UUID = UUID()
    var name: String
    var emoji: String = "•"
    var flow: MoneyFlow = .expense
    var kind: SpendKind = .flexible
    var isArchived: Bool = false

    var displayName: String { "\(emoji) \(name)" }
}

struct Txn: Identifiable, Codable, Hashable {
    var id: UUID = UUID()
    var date: Date = Date()
    /// Всегда положительное число, знак определяется полем `flow`.
    var amount: Double = 0
    var flow: MoneyFlow = .expense
    var categoryID: UUID? = nil
    var note: String = ""

    /// Со знаком: доход «+», расход «−».
    var signedAmount: Double { flow == .income ? amount : -amount }
}

/// Перевод денег в цель (или изъятие из неё, если сумма отрицательная).
struct Contribution: Identifiable, Codable, Hashable {
    var id: UUID = UUID()
    var goalID: UUID
    var date: Date = Date()
    var amount: Double = 0
    var note: String = ""
}

struct Goal: Identifiable, Codable, Hashable {
    var id: UUID = UUID()
    var title: String = ""
    var emoji: String = "🎯"
    var targetAmount: Double = 0
    /// Уже накоплено до начала учёта в приложении.
    var startingAmount: Double = 0
    var deadline: Date? = nil
    /// Меньше — важнее. Определяет очередь в режиме «по очереди».
    var priority: Int = 0
    /// Доля месячного темпа (0...1) в режиме «параллельно, долями».
    var share: Double = 0.5
    var colorHex: String = "#4F8DF7"
    var isArchived: Bool = false
    var note: String = ""
}

struct Profile: Codable, Hashable {
    var currencyCode: String = "EUR"
    /// Остаток на счетах на момент старта учёта (не считая того, что уже лежит в целях).
    var openingBalance: Double = 0
    var plannedIncome: Double = 0
    var essentialsPlan: Double = 0
    /// Лимит свободных трат в месяц — база для «красной зоны».
    var flexibleLimit: Double = 500
    /// План откладывать в месяц.
    var savingsPlan: Double = 1000
    var paceMode: PaceMode = .weighted
    var manualPace: Double = 1500
    var fundingMode: FundingMode = .priority
}

struct AppData: Codable {
    var schemaVersion: Int = 1
    var profile: Profile = Profile()
    var categories: [Category] = []
    var goals: [Goal] = []
    var transactions: [Txn] = []
    var contributions: [Contribution] = []
}

// MARK: - Месяц как ключ

/// Год + месяц. Сравнимый, хешируемый, удобен как ось для графиков.
struct MonthKey: Hashable, Comparable, Codable, Identifiable {
    var year: Int
    var month: Int

    var id: Int { year * 100 + month }

    init(year: Int, month: Int) {
        self.year = year
        self.month = month
    }

    init(date: Date, calendar: Calendar = Cal.ru) {
        let parts = calendar.dateComponents([.year, .month], from: date)
        self.year = parts.year ?? 2000
        self.month = parts.month ?? 1
    }

    static func < (lhs: MonthKey, rhs: MonthKey) -> Bool { lhs.id < rhs.id }

    /// Сквозной номер месяца — упрощает арифметику.
    var index: Int { year * 12 + (month - 1) }

    static func from(index: Int) -> MonthKey {
        let y = Int((Double(index) / 12.0).rounded(.down))
        let m = index - y * 12 + 1
        return MonthKey(year: y, month: m)
    }

    func adding(_ months: Int) -> MonthKey { MonthKey.from(index: index + months) }

    static func distance(from: MonthKey, to: MonthKey) -> Int { to.index - from.index }

    var startDate: Date {
        var parts = DateComponents()
        parts.year = year
        parts.month = month
        parts.day = 1
        return Cal.ru.date(from: parts) ?? Date()
    }

    var endDate: Date {
        Cal.ru.date(byAdding: DateComponents(month: 1, day: -1), to: startDate) ?? startDate
    }

    var daysInMonth: Int {
        Cal.ru.range(of: .day, in: .month, for: startDate)?.count ?? 30
    }

    static var current: MonthKey { MonthKey(date: Date()) }

    /// «сен 26» — для плотных подписей на оси графика.
    var shortTitle: String { Fmt.monthShort.string(from: startDate) }

    /// «Сентябрь 2026» — для заголовков.
    var fullTitle: String { Fmt.monthFull.string(from: startDate).capitalizedFirst }

    /// «сентябрь 2026» — для списков.
    var listTitle: String { Fmt.monthFull.string(from: startDate) }
}

// MARK: - Календарь и форматтеры

enum Cal {
    /// Один календарь на всё приложение: неделя с понедельника, русская локаль.
    static let ru: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.locale = Locale(identifier: "ru_RU")
        c.firstWeekday = 2
        return c
    }()
}

enum Fmt {
    static let locale = Locale(identifier: "ru_RU")

    static let monthShort: DateFormatter = {
        let f = DateFormatter()
        f.locale = locale
        f.calendar = Cal.ru
        f.dateFormat = "LLL yy"
        return f
    }()

    static let monthFull: DateFormatter = {
        let f = DateFormatter()
        f.locale = locale
        f.calendar = Cal.ru
        f.dateFormat = "LLLL yyyy"
        return f
    }()

    static let dayLong: DateFormatter = {
        let f = DateFormatter()
        f.locale = locale
        f.calendar = Cal.ru
        f.dateFormat = "d MMMM, EEEE"
        return f
    }()

    static let dayShort: DateFormatter = {
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

    static func money(_ value: Double, code: String, fraction: Bool = false) -> String {
        let safe = value.isFinite ? value : 0
        let f = moneyFormatter(code: code, fraction: fraction)
        return f.string(from: NSNumber(value: safe)) ?? "\(Int(safe))"
    }

    static func signedMoney(_ value: Double, code: String, fraction: Bool = false) -> String {
        let body = money(abs(value), code: code, fraction: fraction)
        if value > 0 { return "+" + body }
        if value < 0 { return "−" + body }
        return body
    }

    static func symbol(for code: String) -> String {
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

    static func percent(_ value: Double, digits: Int = 0) -> String {
        let safe = value.isFinite ? value : 0
        return String(format: "%.\(digits)f%%", safe * 100)
    }

    /// «3 месяца», «1 месяц», «7 месяцев» — с правильным окончанием.
    static func monthsWord(_ count: Int) -> String {
        let n = abs(count) % 100
        let n1 = n % 10
        if n > 10 && n < 20 { return "\(count) месяцев" }
        if n1 == 1 { return "\(count) месяц" }
        if n1 >= 2 && n1 <= 4 { return "\(count) месяца" }
        return "\(count) месяцев"
    }

    static func daysWord(_ count: Int) -> String {
        let n = abs(count) % 100
        let n1 = n % 10
        if n > 10 && n < 20 { return "\(count) дней" }
        if n1 == 1 { return "\(count) день" }
        if n1 >= 2 && n1 <= 4 { return "\(count) дня" }
        return "\(count) дней"
    }

    /// Человекочитаемый срок: «4 месяца», «1 год 3 месяца», «больше 15 лет».
    static func horizon(months: Double) -> String {
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
    var capitalizedFirst: String {
        guard let first = self.first else { return self }
        return String(first).uppercased() + self.dropFirst()
    }
}

extension Double {
    /// Защита от NaN/бесконечностей, которые ломают вёрстку и графики.
    var finiteOrZero: Double { isFinite ? self : 0 }

    func clamped(_ lower: Double, _ upper: Double) -> Double {
        Swift.min(Swift.max(self, lower), upper)
    }
}
