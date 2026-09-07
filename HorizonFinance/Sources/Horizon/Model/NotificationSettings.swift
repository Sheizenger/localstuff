import Foundation

/// Что приложению разрешено сообщать. Всё выключается по отдельности:
/// уведомление, которое не помогает, быстро приучает игнорировать остальные.
struct NotificationSettings: Codable, Hashable {
    /// Общий выключатель. Включается только после того, как система дала разрешение.
    var enabled: Bool = false
    /// Пересечение порогов лимита свободных трат: 60%, 85%, 100%.
    var limitThresholds: Bool = true
    /// Напоминание о предстоящем регулярном платеже.
    var upcomingPayments: Bool = true
    /// За сколько дней предупреждать.
    var leadDays: Int = 2
    /// Итог закрытого месяца в первый день нового.
    var monthSummary: Bool = true
    /// В день поступления дохода — напоминание перевести в цели до трат.
    var payday: Bool = true

    enum CodingKeys: String, CodingKey {
        case enabled, limitThresholds, upcomingPayments, leadDays, monthSummary, payday
    }
}

extension NotificationSettings {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        var settings = NotificationSettings()
        settings.enabled = try container.decodeIfPresent(Bool.self, forKey: .enabled) ?? false
        settings.limitThresholds = try container.decodeIfPresent(Bool.self, forKey: .limitThresholds) ?? true
        settings.upcomingPayments = try container.decodeIfPresent(Bool.self, forKey: .upcomingPayments) ?? true
        settings.leadDays = try container.decodeIfPresent(Int.self, forKey: .leadDays) ?? 2
        settings.monthSummary = try container.decodeIfPresent(Bool.self, forKey: .monthSummary) ?? true
        settings.payday = try container.decodeIfPresent(Bool.self, forKey: .payday) ?? true
        self = settings
    }
}

/// Готовое уведомление: либо доставить сейчас, либо запланировать на дату.
struct PlannedNotification: Identifiable, Hashable {
    /// Ключ дедупликации — одно и то же событие не повторяется.
    var id: String
    var title: String
    var body: String
    /// nil — доставить немедленно.
    var date: Date? = nil
}
