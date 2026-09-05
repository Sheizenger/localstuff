import Foundation

/// Периодичность повторяющейся операции.
enum RecurrenceUnit: String, Codable, CaseIterable, Identifiable, Hashable {
    case week
    case month
    case year

    var id: String { rawValue }

    var title: String {
        switch self {
        case .week: return "Каждую неделю"
        case .month: return "Каждый месяц"
        case .year: return "Раз в год"
        }
    }

    var shortTitle: String {
        switch self {
        case .week: return "неделя"
        case .month: return "месяц"
        case .year: return "год"
        }
    }
}

/// Шаблон повторяющейся операции: аренда, коммуналка, подписка, зарплата.
///
/// Приложение само создаёт операции по шаблону — иначе обязательные расходы,
/// которые и так известны заранее, приходится вбивать руками каждый месяц.
struct RecurringRule: Identifiable, Codable, Hashable {
    var id: UUID = UUID()
    var title: String = ""
    var amount: Double = 0
    var flow: MoneyFlow = .expense
    var categoryID: UUID? = nil
    var note: String = ""

    var unit: RecurrenceUnit = .month
    /// Каждые N единиц: 1 — каждый месяц, 3 — раз в квартал.
    var interval: Int = 1
    /// День месяца для месячных и годовых правил; если в месяце меньше дней — берётся последний.
    var dayOfMonth: Int = 1
    /// День недели для недельных правил: 1 — воскресенье, 2 — понедельник.
    var weekday: Int = 2
    /// Месяц для годовых правил.
    var monthOfYear: Int = 1

    var startDate: Date = Date()
    var endDate: Date? = nil
    var isActive: Bool = true
    /// Создавать операции автоматически или только показывать как ожидаемые.
    var autoCreate: Bool = true
    /// До какой даты операции по этому шаблону уже созданы.
    var lastCreatedDate: Date? = nil

    var signedAmount: Double { flow == .income ? amount : -amount }

    var scheduleTitle: String {
        switch unit {
        case .week:
            let names = ["", "воскресеньям", "понедельникам", "вторникам", "средам",
                         "четвергам", "пятницам", "субботам"]
            let name = (weekday >= 1 && weekday <= 7) ? names[weekday] : "понедельникам"
            return interval == 1 ? "по \(name)" : "по \(name), раз в \(interval) нед."
        case .month:
            return interval == 1 ? "\(dayOfMonth)-го числа" : "\(dayOfMonth)-го числа, раз в \(interval) мес."
        case .year:
            let month = Cal.ru.monthSymbols
            let name = (monthOfYear >= 1 && monthOfYear <= 12) ? month[monthOfYear - 1] : ""
            return "\(dayOfMonth) \(name)"
        }
    }

    enum CodingKeys: String, CodingKey {
        case id, title, amount, flow, categoryID, note
        case unit, interval, dayOfMonth, weekday, monthOfYear
        case startDate, endDate, isActive, autoCreate, lastCreatedDate
    }
}

extension RecurringRule {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        var rule = RecurringRule()
        rule.id = try container.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        rule.title = try container.decodeIfPresent(String.self, forKey: .title) ?? ""
        rule.amount = try container.decodeIfPresent(Double.self, forKey: .amount) ?? 0
        rule.flow = try container.decodeIfPresent(MoneyFlow.self, forKey: .flow) ?? .expense
        rule.categoryID = try container.decodeIfPresent(UUID.self, forKey: .categoryID)
        rule.note = try container.decodeIfPresent(String.self, forKey: .note) ?? ""
        rule.unit = try container.decodeIfPresent(RecurrenceUnit.self, forKey: .unit) ?? .month
        rule.interval = try container.decodeIfPresent(Int.self, forKey: .interval) ?? 1
        rule.dayOfMonth = try container.decodeIfPresent(Int.self, forKey: .dayOfMonth) ?? 1
        rule.weekday = try container.decodeIfPresent(Int.self, forKey: .weekday) ?? 2
        rule.monthOfYear = try container.decodeIfPresent(Int.self, forKey: .monthOfYear) ?? 1
        rule.startDate = try container.decodeIfPresent(Date.self, forKey: .startDate) ?? Date()
        rule.endDate = try container.decodeIfPresent(Date.self, forKey: .endDate)
        rule.isActive = try container.decodeIfPresent(Bool.self, forKey: .isActive) ?? true
        rule.autoCreate = try container.decodeIfPresent(Bool.self, forKey: .autoCreate) ?? true
        rule.lastCreatedDate = try container.decodeIfPresent(Date.self, forKey: .lastCreatedDate)
        self = rule
    }
}

/// Ближайшее срабатывание правила — для списка «ожидается».
struct UpcomingEntry: Identifiable {
    var rule: RecurringRule
    var date: Date
    var id: String { "\(rule.id.uuidString)-\(date.timeIntervalSince1970)" }
}
