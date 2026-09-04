import Foundation
import SwiftUI

/// Единственный источник правды. Хранит данные, отдаёт аналитику и сам пишет файл на диск.
final class Store: ObservableObject {

    @Published var data: AppData {
        didSet { scheduleSave() }
    }

    /// Отметка последнего сохранения — показывается в настройках.
    @Published private(set) var lastSavedAt: Date? = nil
    @Published private(set) var saveError: String? = nil

    private var saveWork: DispatchWorkItem? = nil

    init(data: AppData? = nil) {
        if let data = data {
            self.data = data
        } else if let loaded = Persistence.load() {
            self.data = loaded
        } else {
            self.data = AppData.starter()
        }
    }

    // MARK: Аналитика

    var analytics: Analytics { Analytics(data: data) }

    var currency: String { data.profile.currencyCode }

    var forecasts: [GoalForecast] {
        let a = analytics
        return Forecaster.build(
            goals: a.activeGoals,
            pace: a.pace.value,
            savedFor: { a.saved(for: $0) }
        )
    }

    func forecast(for goal: Goal) -> GoalForecast? {
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

    func saveNow() {
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

    func addTransaction(_ txn: Txn) {
        data.transactions.append(txn)
        data.transactions.sort { $0.date > $1.date }
    }

    func updateTransaction(_ txn: Txn) {
        guard let index = data.transactions.firstIndex(where: { $0.id == txn.id }) else { return }
        data.transactions[index] = txn
        data.transactions.sort { $0.date > $1.date }
    }

    func deleteTransaction(_ txn: Txn) {
        data.transactions.removeAll { $0.id == txn.id }
    }

    func deleteTransactions(ids: Set<UUID>) {
        data.transactions.removeAll { ids.contains($0.id) }
    }

    // MARK: Цели

    func addGoal(_ goal: Goal) {
        var goal = goal
        if goal.priority == 0 {
            goal.priority = (data.goals.map { $0.priority }.max() ?? -1) + 1
        }
        data.goals.append(goal)
    }

    func updateGoal(_ goal: Goal) {
        guard let index = data.goals.firstIndex(where: { $0.id == goal.id }) else { return }
        data.goals[index] = goal
    }

    /// Быстрое переключение режима прямо из карточки цели.
    func toggleFunding(_ goal: Goal) {
        guard let index = data.goals.firstIndex(where: { $0.id == goal.id }) else { return }
        data.goals[index].funding = data.goals[index].funding == .parallel ? .queued : .parallel
        // Параллельная цель с нулевой долей не получала бы ничего — даём осмысленный минимум.
        if data.goals[index].funding == .parallel && data.goals[index].share <= 0 {
            data.goals[index].share = 0.25
        }
    }

    func deleteGoal(_ goal: Goal) {
        data.goals.removeAll { $0.id == goal.id }
        data.contributions.removeAll { $0.goalID == goal.id }
    }

    func moveGoal(_ goal: Goal, up: Bool) {
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

    func addContribution(_ contribution: Contribution) {
        data.contributions.append(contribution)
        data.contributions.sort { $0.date > $1.date }
    }

    func deleteContribution(_ contribution: Contribution) {
        data.contributions.removeAll { $0.id == contribution.id }
    }

    func contributions(for goal: Goal) -> [Contribution] {
        data.contributions.filter { $0.goalID == goal.id }.sorted { $0.date > $1.date }
    }

    // MARK: Категории

    func addCategory(_ category: Category) {
        data.categories.append(category)
    }

    func updateCategory(_ category: Category) {
        guard let index = data.categories.firstIndex(where: { $0.id == category.id }) else { return }
        data.categories[index] = category
    }

    func deleteCategory(_ category: Category) {
        // Операции не удаляем — просто теряют категорию и считаются свободными тратами.
        data.categories.removeAll { $0.id == category.id }
        for index in data.transactions.indices where data.transactions[index].categoryID == category.id {
            data.transactions[index].categoryID = nil
        }
    }

    func categories(for flow: MoneyFlow) -> [Category] {
        data.categories.filter { $0.flow == flow && !$0.isArchived }
    }

    // MARK: Чеки

    /// Запоминает, каким товаром пользователь считает эту строку чека.
    func rememberAlias(text: String, productID: String) {
        let key = ProductMatcher.aliasKey(for: text)
        guard !key.isEmpty else { return }
        data.receiptAliases[key] = productID
    }

    func category(named name: String, flow: MoneyFlow) -> Category? {
        data.categories.first(where: { $0.flow == flow && $0.name.caseInsensitiveCompare(name) == .orderedSame })
    }

    /// Записывает разобранный чек в операции.
    ///
    /// По умолчанию это одна операция «Продукты», внутри которой лежат все позиции.
    /// Если попросили разнести — бытовое и алкоголь уходят отдельной свободной тратой,
    /// потому что в приложении именно они съедают месячный лимит.
    @discardableResult
    func importReceipt(_ receipt: ParsedReceipt, splitFlexible: Bool, updateBasketPrices: Bool) -> [Txn] {
        let date = receipt.date ?? Date()
        let merchant = receipt.merchantName
        var note = merchant.isEmpty ? "Чек" : "Чек: \(merchant)"
        if let code = receipt.receiptCode { note += " · \(code)" }

        // Чек из бургерной — это не продукты домой, и в лимит он попадает по-другому.
        let mainCategory = ReceiptParser.isFastFood(merchant) ? "Фаст-фуд" : "Продукты"

        let flexibleLines = receipt.lines.filter { $0.category == .household || $0.productID == "alcohol" }
        let foodLines = receipt.lines.filter { !($0.category == .household || $0.productID == "alcohol") }
        let flexibleTotal = flexibleLines.reduce(0.0) { $0 + $1.amount }

        var created: [Txn] = []

        if splitFlexible && flexibleTotal > 0.01 && !foodLines.isEmpty {
            let foodTotal = foodLines.reduce(0.0) { $0 + $1.amount }

            var food = Txn()
            food.date = date
            food.amount = (foodTotal * 100).rounded() / 100
            food.flow = .expense
            food.categoryID = category(named: mainCategory, flow: .expense)?.id
            food.note = note
            food.merchant = merchant
            food.receiptLines = foodLines
            created.append(food)

            var flexible = Txn()
            flexible.date = date
            flexible.amount = (flexibleTotal * 100).rounded() / 100
            flexible.flow = .expense
            flexible.categoryID = category(named: "Дом и обустройство", flow: .expense)?.id
                ?? categories(for: .expense).first(where: { $0.kind == .flexible })?.id
            flexible.note = note + " · бытовое и напитки"
            flexible.merchant = merchant
            flexible.receiptLines = flexibleLines
            created.append(flexible)
        } else {
            var txn = Txn()
            txn.date = date
            txn.amount = (receipt.amountToRecord * 100).rounded() / 100
            txn.flow = .expense
            txn.categoryID = category(named: mainCategory, flow: .expense)?.id
            txn.note = note
            txn.merchant = merchant
            txn.receiptLines = receipt.lines
            created.append(txn)
        }

        for txn in created where txn.amount > 0 {
            data.transactions.append(txn)
        }
        data.transactions.sort { $0.date > $1.date }

        if updateBasketPrices, let chainID = receipt.chainID {
            applyReceiptPrices(receipt, chainID: chainID)
        }

        return created
    }

    /// Цены с реального чека важнее модельных — переносим их в корзину.
    private func applyReceiptPrices(_ receipt: ParsedReceipt, chainID: String) {
        for line in receipt.lines {
            guard !line.isDiscount, let productID = line.productID else { continue }
            guard line.quantity > 0.0001, line.amount > 0 else { continue }
            let unit = (line.unitPrice * 100).rounded() / 100
            guard unit > 0.01, unit < 500 else { continue }
            let key = BasketSettings.overrideKey(chainID: chainID, productID: productID)
            data.basket.priceOverrides[key] = unit
        }
    }

    // MARK: Данные целиком

    func loadDemoData() {
        data = AppData.demo()
        saveNow()
    }

    func resetAll() {
        data = AppData.starter()
        saveNow()
    }

    func replace(with newData: AppData) {
        data = newData
        saveNow()
    }
}
