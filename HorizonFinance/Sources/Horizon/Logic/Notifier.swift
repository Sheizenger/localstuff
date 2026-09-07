import Foundation
import UserNotifications

/// Тонкая обёртка над системными уведомлениями.
///
/// Важно: `UNUserNotificationCenter` работает только внутри собранного бандла.
/// При запуске через `swift run` обращение к нему роняет процесс, поэтому всё,
/// что здесь есть, сначала проверяет `isSupported`.
enum Notifier {

    static var isSupported: Bool {
        Bundle.main.bundleIdentifier != nil && Bundle.main.bundleURL.pathExtension == "app"
    }

    private static var center: UNUserNotificationCenter? {
        guard isSupported else { return nil }
        return UNUserNotificationCenter.current()
    }

    // MARK: Разрешение

    static func requestAuthorization(completion: @escaping (Bool) -> Void) {
        guard let center = center else {
            completion(false)
            return
        }
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            DispatchQueue.main.async { completion(granted) }
        }
    }

    static func checkAuthorization(completion: @escaping (Bool) -> Void) {
        guard let center = center else {
            completion(false)
            return
        }
        center.getNotificationSettings { settings in
            let granted = settings.authorizationStatus == .authorized
                || settings.authorizationStatus == .provisional
            DispatchQueue.main.async { completion(granted) }
        }
    }

    // MARK: Отправка

    static func deliver(id: String, title: String, body: String) {
        schedule(id: id, title: title, body: body, at: nil)
    }

    static func schedule(id: String, title: String, body: String, at date: Date?) {
        guard let center = center else { return }

        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default

        var trigger: UNNotificationTrigger? = nil
        if let date = date, date > Date() {
            let parts = Cal.ru.dateComponents([.year, .month, .day, .hour, .minute], from: date)
            trigger = UNCalendarNotificationTrigger(dateMatching: parts, repeats: false)
        }

        let request = UNNotificationRequest(identifier: id, content: content, trigger: trigger)
        center.add(request, withCompletionHandler: nil)
    }

    static func cancelAllPending() {
        center?.removeAllPendingNotificationRequests()
    }
}
