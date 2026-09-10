import Foundation
import SwiftUI

/// Единственный источник правды. Хранит данные, отдаёт аналитику и сам пишет файл на диск.
public final class Store: ObservableObject {

    @Published public var data: AppData {
        didSet { scheduleSave() }
    }

    /// Отметка последнего сохранения — показывается в настройках.
    @Published public private(set) var lastSavedAt: Date? = nil
    @Published public private(set) var saveError: String? = nil

    private var saveWork: DispatchWorkItem? = nil

    public init(data: AppData? = nil) {
        if let data = data {
            self.data = data
        } else if let loaded = Persistence.load() {
            self.data = loaded
        } else {
            self.data = AppData.starter()
        }
    }

    // MARK: Аналитика

    public var analytics: Analytics { Analytics(data: data) }

    public var currency: String { data.profile.currencyCode }

    public var forecasts: [GoalForecast] {
        let a = analytics
        return Forecaster.build(
            goals: a.activeGoals,
            pace: a.pace.value,
            mode: data.profile.fundingMode,
            savedFor: { a.saved(for: $0) }
        )
    }

    public func forecast(for goal: Goal) -> GoalForecast? {
        forecasts.first(where: { $0.goal.id == goal.id })
    }

    // MARK: Сохранение

    private func scheduleSave() {
        saveWork?.cancel()
        let snapshot = data
        let work = DispatchWorkItem { [weak self] in
            let ok = Persistence.save(snapshot)
            DispatchQueue.main.async {
                guard let self = self else { return }
                if ok {
                    self.lastSavedAt = Date()
                    self.saveError = nil
                } else {
                    self.saveError = "Не удалось записать файл данных"
                }
            }
        }
        saveWork = work
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 0.4, execute: work)
    }

    public func saveNow() {
        saveWork?.cancel()
        let ok = Persistence.save(data)
        if ok {
            lastSavedAt = Date()
            saveError = nil
        } else {
            saveError = "Не удалось записать файл данных"
        }
    }

    // MARK: Операции

    public func addTransaction(_ txn: Txn) {
        data.transactions.append(txn)
        data.transactions.sort { $0.date > $1.date }
    }

    public func updateTransaction(_ txn: Txn) {
        guard let index = data.transactions.firstIndex(where: { $0.id == txn.id }) else { return }
        data.transactions[index] = txn
        data.transactions.sort { $0.date > $1.date }
    }

    public func deleteTransaction(_ txn: Txn) {
        data.transactions.removeAll { $0.id == txn.id }
    }

    public func deleteTransactions(ids: Set<UUID>) {
        data.transactions.removeAll { ids.contains($0.id) }
    }

    // MARK: Цели

    public func addGoal(_ goal: Goal) {
        var goal = goal
        if goal.priority == 0 {
            goal.priority = (data.goals.map { $0.priority }.max() ?? -1) + 1
        }
        data.goals.append(goal)
    }

    public func updateGoal(_ goal: Goal) {
        guard let index = data.goals.firstIndex(where: { $0.id == goal.id }) else { return }
        data.goals[index] = goal
    }

    public func deleteGoal(_ goal: Goal) {
        data.goals.removeAll { $0.id == goal.id }
        data.contributions.removeAll { $0.goalID == goal.id }
    }

    public func moveGoal(_ goal: Goal, up: Bool) {
        var ordered = analytics.activeGoals
        guard let index = ordered.firstIndex(where: { $0.id == goal.id }) else { return }
        let target = up ? index - 1 : index + 1
        guard target >= 0 && target < ordered.count else { return }
        ordered.swapAt(index, target)
        for (i, g) in ordered.enumerated() {
            if let realIndex = data.goals.firstIndex(where: { $0.id == g.id }) {
                data.goals[realIndex].priority = i
            }
        }
    }

    // MARK: Пополнения целей

    public func addContribution(_ contribution: Contribution) {
        data.contributions.append(contribution)
        data.contributions.sort { $0.date > $1.date }
    }

    public func deleteContribution(_ contribution: Contribution) {
        data.contributions.removeAll { $0.id == contribution.id }
    }

    public func contributions(for goal: Goal) -> [Contribution] {
        data.contributions.filter { $0.goalID == goal.id }.sorted { $0.date > $1.date }
    }

    // MARK: Категории

    public func addCategory(_ category: Category) {
        data.categories.append(category)
    }

    public func updateCategory(_ category: Category) {
        guard let index = data.categories.firstIndex(where: { $0.id == category.id }) else { return }
        data.categories[index] = category
    }

    public func deleteCategory(_ category: Category) {
        // Операции не удаляем — просто теряют категорию и считаются свободными тратами.
        data.categories.removeAll { $0.id == category.id }
        for index in data.transactions.indices where data.transactions[index].categoryID == category.id {
            data.transactions[index].categoryID = nil
        }
    }

    public func categories(for flow: MoneyFlow) -> [Category] {
        data.categories.filter { $0.flow == flow && !$0.isArchived }
    }

    // MARK: Данные целиком

    public func loadDemoData() {
        data = AppData.demo()
        saveNow()
    }

    public func resetAll() {
        data = AppData.starter()
        saveNow()
    }

    public func replace(with newData: AppData) {
        data = newData
        saveNow()
    }
}
