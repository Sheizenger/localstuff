import SwiftUI

public enum AppSection: String, CaseIterable, Identifiable, Hashable {
    case dashboard
    case transactions
    case goals
    case analytics
    case settings

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .dashboard: return "Обзор"
        case .transactions: return "Операции"
        case .goals: return "Цели"
        case .analytics: return "Аналитика"
        case .settings: return "Настройки"
        }
    }

    public var icon: String {
        switch self {
        case .dashboard: return "square.grid.2x2"
        case .transactions: return "list.bullet.rectangle"
        case .goals: return "target"
        case .analytics: return "chart.bar.xaxis"
        case .settings: return "gearshape"
        }
    }

    public var subtitle: String {
        switch self {
        case .dashboard: return "Запас месяца и ближайший горизонт"
        case .transactions: return "Доходы, расходы и переводы в цели"
        case .goals: return "Сроки достижения при текущем темпе"
        case .analytics: return "Помесячная картина и прогноз"
        case .settings: return "Лимиты, темп, категории, данные"
        }
    }
}

/// Общая шина для меню, горячих клавиш и модальных окон.
public final class UIBus: ObservableObject {
    @Published public var section: AppSection = .dashboard
    @Published public var showAddTransaction: Bool = false
    @Published public var showAddGoal: Bool = false
    /// Цель, для которой открыт диалог пополнения.
    @Published public var contributionTarget: Goal? = nil

    public init() {}
}
