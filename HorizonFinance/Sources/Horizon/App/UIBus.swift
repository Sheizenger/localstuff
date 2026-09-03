import SwiftUI

enum AppSection: String, CaseIterable, Identifiable, Hashable {
    case dashboard
    case transactions
    case goals
    case basket
    case analytics
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .dashboard: return "Обзор"
        case .transactions: return "Операции"
        case .goals: return "Цели"
        case .basket: return "Продукты"
        case .analytics: return "Аналитика"
        case .settings: return "Настройки"
        }
    }

    var icon: String {
        switch self {
        case .dashboard: return "square.grid.2x2"
        case .transactions: return "list.bullet.rectangle"
        case .goals: return "target"
        case .basket: return "cart"
        case .analytics: return "chart.bar.xaxis"
        case .settings: return "gearshape"
        }
    }

    var subtitle: String {
        switch self {
        case .dashboard: return "Запас месяца и ближайший горизонт"
        case .transactions: return "Доходы, расходы и переводы в цели"
        case .goals: return "Сроки достижения при текущем темпе"
        case .basket: return "Корзина по городу, сетям и составу семьи"
        case .analytics: return "Помесячная картина и прогноз"
        case .settings: return "Лимиты, темп, категории, данные"
        }
    }
}

/// Общая шина для меню, горячих клавиш и модальных окон.
final class UIBus: ObservableObject {
    @Published var section: AppSection = .dashboard
    @Published var showAddTransaction: Bool = false
    @Published var showAddGoal: Bool = false
    /// Цель, для которой открыт диалог пополнения.
    @Published var contributionTarget: Goal? = nil
}
