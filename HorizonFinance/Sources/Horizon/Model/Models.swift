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

/// Как финансируется конкретная цель. Режим свой у каждой цели:
/// часть целей может копиться параллельно долями, часть — стоять в общей очереди.
enum GoalFunding: String, Codable, CaseIterable, Hashable, Identifiable {
    case parallel
    case queued

    var id: String { rawValue }

    var title: String {
        switch self {
        case .parallel: return "Параллельно"
        case .queued: return "В очереди"
        }
    }

    var shortTitle: String {
        switch self {
        case .parallel: return "параллельно"
        case .queued: return "в очереди"
        }
    }

    var hint: String {
        switch self {
        case .parallel: return "Цель получает свою долю темпа каждый месяц, начиная с сегодня"
        case .queued: return "Цель копится из того, что не разобрали параллельные цели, и по очереди приоритета"
        }
    }

    var icon: String {
        switch self {
        case .parallel: return "arrow.triangle.branch"
        case .queued: return "list.number"
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
    /// Магазин из чека, если операция пришла из распознавания.
    var merchant: String = ""
    /// Разбор чека: позиции с ценами и категориями. Пусто у обычных операций.
    var receiptLines: [ReceiptLine] = []
    /// Шаблон, по которому операция создана автоматически.
    var recurringID: UUID? = nil

    /// Со знаком: доход «+», расход «−».
    var signedAmount: Double { flow == .income ? amount : -amount }

    var hasReceipt: Bool { !receiptLines.isEmpty }

    enum CodingKeys: String, CodingKey {
        case id, date, amount, flow, categoryID, note, merchant, receiptLines, recurringID
    }
}

extension Txn {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        var txn = Txn()
        txn.id = try container.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        txn.date = try container.decodeIfPresent(Date.self, forKey: .date) ?? Date()
        txn.amount = try container.decodeIfPresent(Double.self, forKey: .amount) ?? 0
        txn.flow = try container.decodeIfPresent(MoneyFlow.self, forKey: .flow) ?? .expense
        txn.categoryID = try container.decodeIfPresent(UUID.self, forKey: .categoryID)
        txn.note = try container.decodeIfPresent(String.self, forKey: .note) ?? ""
        txn.merchant = try container.decodeIfPresent(String.self, forKey: .merchant) ?? ""
        txn.receiptLines = try container.decodeIfPresent([ReceiptLine].self, forKey: .receiptLines) ?? []
        txn.recurringID = try container.decodeIfPresent(UUID.self, forKey: .recurringID)
        self = txn
    }
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
    /// Меньше — важнее. Определяет порядок в очереди и порядок карточек.
    var priority: Int = 0
    /// Доля месячного темпа (0...1) для целей, которые копятся параллельно.
    var share: Double = 0.5
    var colorHex: String = "#4F8DF7"
    var isArchived: Bool = false
    var note: String = ""
    /// Своя для каждой цели: копится параллельно долей или ждёт очереди.
    var funding: GoalFunding = .queued

    enum CodingKeys: String, CodingKey {
        case id, title, emoji, targetAmount, startingAmount, deadline
        case priority, share, colorHex, isArchived, note, funding
    }
}

// Разбор в расширении, а не в теле структуры: так сохраняется автоматический
// поэлементный инициализатор, а старые файлы без новых полей продолжают читаться.
extension Goal {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        var goal = Goal()
        goal.id = try container.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        goal.title = try container.decodeIfPresent(String.self, forKey: .title) ?? ""
        goal.emoji = try container.decodeIfPresent(String.self, forKey: .emoji) ?? "🎯"
        goal.targetAmount = try container.decodeIfPresent(Double.self, forKey: .targetAmount) ?? 0
        goal.startingAmount = try container.decodeIfPresent(Double.self, forKey: .startingAmount) ?? 0
        goal.deadline = try container.decodeIfPresent(Date.self, forKey: .deadline)
        goal.priority = try container.decodeIfPresent(Int.self, forKey: .priority) ?? 0
        goal.share = try container.decodeIfPresent(Double.self, forKey: .share) ?? 0.5
        goal.colorHex = try container.decodeIfPresent(String.self, forKey: .colorHex) ?? "#4F8DF7"
        goal.isArchived = try container.decodeIfPresent(Bool.self, forKey: .isArchived) ?? false
        goal.note = try container.decodeIfPresent(String.self, forKey: .note) ?? ""
        goal.funding = try container.decodeIfPresent(GoalFunding.self, forKey: .funding) ?? .queued
        self = goal
    }
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

    enum CodingKeys: String, CodingKey {
        case currencyCode, openingBalance, plannedIncome, essentialsPlan
        case flexibleLimit, savingsPlan, paceMode, manualPace
    }
}

extension Profile {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        var profile = Profile()
        profile.currencyCode = try container.decodeIfPresent(String.self, forKey: .currencyCode) ?? "EUR"
        profile.openingBalance = try container.decodeIfPresent(Double.self, forKey: .openingBalance) ?? 0
        profile.plannedIncome = try container.decodeIfPresent(Double.self, forKey: .plannedIncome) ?? 0
        profile.essentialsPlan = try container.decodeIfPresent(Double.self, forKey: .essentialsPlan) ?? 0
        profile.flexibleLimit = try container.decodeIfPresent(Double.self, forKey: .flexibleLimit) ?? 500
        profile.savingsPlan = try container.decodeIfPresent(Double.self, forKey: .savingsPlan) ?? 1000
        profile.paceMode = try container.decodeIfPresent(PaceMode.self, forKey: .paceMode) ?? .weighted
        profile.manualPace = try container.decodeIfPresent(Double.self, forKey: .manualPace) ?? 1500
        self = profile
    }
}

struct AppData: Codable {
    /// 1 — общий режим распределения на всё приложение; 2 — режим у каждой цели свой;
    /// 3 — в стандартных категориях появился фаст-фуд.
    var schemaVersion: Int = 3
    var profile: Profile = Profile()
    var categories: [Category] = []
    var goals: [Goal] = []
    var transactions: [Txn] = []
    var contributions: [Contribution] = []
    var basket: BasketSettings = BasketSettings()
    /// Чему научился разбор чеков: нормализованная строка из чека → товар справочника.
    var receiptAliases: [String: String] = [:]
    /// Шаблоны повторяющихся операций: аренда, подписки, зарплата.
    var recurring: [RecurringRule] = []
    /// Чему научился импорт выписки: нормализованное описание → категория приложения.
    var merchantRules: [String: UUID] = [:]

    enum CodingKeys: String, CodingKey {
        case schemaVersion, profile, categories, goals, transactions, contributions
        case basket, receiptAliases, recurring, merchantRules
    }
}

/// Поля профиля, которых больше нет в модели, но которые нужны для чтения старых файлов.
private enum LegacyProfileKeys: String, CodingKey {
    case fundingMode
}

extension AppData {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        var data = AppData()
        let version = try container.decodeIfPresent(Int.self, forKey: .schemaVersion) ?? 1
        data.profile = try container.decodeIfPresent(Profile.self, forKey: .profile) ?? Profile()
        data.categories = try container.decodeIfPresent([Category].self, forKey: .categories) ?? []
        data.goals = try container.decodeIfPresent([Goal].self, forKey: .goals) ?? []
        data.transactions = try container.decodeIfPresent([Txn].self, forKey: .transactions) ?? []
        data.contributions = try container.decodeIfPresent([Contribution].self, forKey: .contributions) ?? []
        data.basket = try container.decodeIfPresent(BasketSettings.self, forKey: .basket) ?? BasketSettings()
        data.receiptAliases = try container.decodeIfPresent([String: String].self, forKey: .receiptAliases) ?? [:]
        data.recurring = try container.decodeIfPresent([RecurringRule].self, forKey: .recurring) ?? []
        data.merchantRules = try container.decodeIfPresent([String: UUID].self, forKey: .merchantRules) ?? [:]

        if version < 2 {
            // Раньше режим распределения был один на все цели и лежал в профиле.
            var legacy: String? = nil
            if let profileContainer = try? container.nestedContainer(keyedBy: LegacyProfileKeys.self, forKey: .profile) {
                legacy = try? profileContainer.decode(String.self, forKey: .fundingMode)
            }
            let migrated: GoalFunding = legacy == "shares" ? .parallel : .queued
            for index in data.goals.indices {
                data.goals[index].funding = migrated
            }
        }

        if version < 3 {
            // Фаст-фуд появился позже: добавляем его тем, у кого набор категорий стандартный.
            let hasFastFood = data.categories.contains {
                $0.name.caseInsensitiveCompare("Фаст-фуд") == .orderedSame
            }
            if !hasFastFood && !data.categories.isEmpty {
                data.categories.append(
                    Category(name: "Фаст-фуд", emoji: "🍔", flow: .expense, kind: .flexible)
                )
            }
        }

        data.schemaVersion = 3
        self = data
    }
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

    static let daySimple: DateFormatter = {
        let f = DateFormatter()
        f.locale = locale
        f.calendar = Cal.ru
        f.dateFormat = "d MMMM"
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

    /// «1 взрослый», «2 взрослых» — для состава семьи.
    static func peopleWord(_ count: Int) -> String {
        let n = abs(count) % 100
        let n1 = n % 10
        if n > 10 && n < 20 { return "\(count) взрослых" }
        if n1 == 1 { return "\(count) взрослый" }
        if n1 >= 2 && n1 <= 4 { return "\(count) взрослых" }
        return "\(count) взрослых"
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
