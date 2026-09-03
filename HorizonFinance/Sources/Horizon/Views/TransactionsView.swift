import SwiftUI

struct TransactionsView: View {
    @EnvironmentObject private var store: Store
    @EnvironmentObject private var bus: UIBus

    enum Tab: String, CaseIterable, Identifiable {
        case operations
        case contributions
        var id: String { rawValue }
        var title: String {
            switch self {
            case .operations: return "Доходы и расходы"
            case .contributions: return "Переводы в цели"
            }
        }
    }

    @State private var month: MonthKey = MonthKey.current
    @State private var tab: Tab = .operations
    @State private var query: String = ""
    @State private var editingTxn: Txn? = nil

    private var currency: String { store.currency }

    var body: some View {
        PageScroll {
            monthBar
            summaryStrip
            Picker("", selection: $tab) {
                ForEach(Tab.allCases) { item in
                    Text(item.title).tag(item)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()

            if tab == .operations {
                operationsList
            } else {
                contributionsList
            }
        }
        .sheet(item: $editingTxn) { txn in
            TransactionEditor(mode: .edit(txn))
                .environmentObject(store)
        }
    }

    // MARK: Переключатель месяца

    private var monthBar: some View {
        HStack(spacing: 12) {
            Button {
                month = month.adding(-1)
            } label: {
                Image(systemName: "chevron.left")
            }
            .buttonStyle(.bordered)
            .help("Предыдущий месяц")

            Text(month.fullTitle)
                .font(.title3.weight(.semibold))
                .frame(minWidth: 190)

            Button {
                month = month.adding(1)
            } label: {
                Image(systemName: "chevron.right")
            }
            .buttonStyle(.bordered)
            .disabled(month >= MonthKey.current)
            .help("Следующий месяц")

            if month != MonthKey.current {
                Button("Текущий месяц") { month = MonthKey.current }
                    .buttonStyle(.link)
            }

            Spacer()

            TextField("Поиск по заметке или категории", text: $query)
                .textFieldStyle(.roundedBorder)
                .frame(width: 260)

            Button {
                bus.showAddTransaction = true
            } label: {
                Label("Добавить", systemImage: "plus")
            }
            .buttonStyle(.borderedProminent)
        }
    }

    // MARK: Итоги месяца

    private var summaryStrip: some View {
        let stats = store.analytics.stats(for: month)
        return HStack(spacing: 12) {
            summaryItem("Доход", Fmt.money(stats.income, code: currency), Palette.green)
            summaryItem("Обязательные", Fmt.money(stats.essential, code: currency), Palette.teal)
            summaryItem("Свободные", Fmt.money(stats.flexible, code: currency), Palette.violet)
            summaryItem("Осталось", Fmt.signedMoney(stats.net, code: currency), stats.net >= 0 ? Palette.green : Palette.red)
            summaryItem("В цели", Fmt.money(stats.moved, code: currency), Palette.accent)
        }
    }

    private func summaryItem(_ title: String, _ value: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption)
                .foregroundStyle(Palette.muted)
            Text(value)
                .font(.system(size: 17, weight: .semibold, design: .rounded))
                .foregroundStyle(color)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(.regularMaterial)
        )
    }

    // MARK: Операции

    private var filteredTxns: [Txn] {
        let analytics = store.analytics
        let text = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return store.data.transactions
            .filter { MonthKey(date: $0.date) == month }
            .filter { txn in
                guard !text.isEmpty else { return true }
                let categoryName = analytics.category(for: txn)?.name.lowercased() ?? ""
                return txn.note.lowercased().contains(text) || categoryName.contains(text)
            }
            .sorted { $0.date > $1.date }
    }

    private struct DayGroup: Identifiable {
        var date: Date
        var items: [Txn]
        var id: Date { date }
    }

    private var groupedTxns: [DayGroup] {
        let grouped = Dictionary(grouping: filteredTxns) { txn in
            Cal.ru.startOfDay(for: txn.date)
        }
        return grouped
            .map { DayGroup(date: $0.key, items: $0.value.sorted { $0.date > $1.date }) }
            .sorted { $0.date > $1.date }
    }

    @ViewBuilder
    private var operationsList: some View {
        if groupedTxns.isEmpty {
            EmptyState(
                icon: "tray",
                title: "В этом месяце пусто",
                message: "Добавьте первую операцию — доход, аренду, продукты или кофе. Прогноз пересчитается автоматически.",
                actionTitle: "Добавить операцию",
                action: { bus.showAddTransaction = true }
            )
            .cardStyle()
        } else {
            ForEach(groupedTxns) { group in
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(Fmt.dayLong.string(from: group.date).capitalizedFirst)
                            .font(.subheadline.weight(.semibold))
                        Spacer()
                        Text(Fmt.signedMoney(group.items.reduce(0.0) { $0 + $1.signedAmount }, code: currency, fraction: true))
                            .font(.subheadline)
                            .foregroundStyle(Palette.muted)
                    }
                    ForEach(group.items) { txn in
                        TransactionRow(txn: txn, currency: currency, category: store.analytics.category(for: txn))
                            .contentShape(Rectangle())
                            .onTapGesture { editingTxn = txn }
                            .contextMenu {
                                Button("Изменить") { editingTxn = txn }
                                Button("Удалить", role: .destructive) { store.deleteTransaction(txn) }
                            }
                        if txn.id != group.items.last?.id {
                            Divider().opacity(0.4)
                        }
                    }
                }
                .cardStyle()
            }
        }
    }

    // MARK: Переводы в цели

    private var filteredContributions: [Contribution] {
        store.data.contributions
            .filter { MonthKey(date: $0.date) == month }
            .sorted { $0.date > $1.date }
    }

    @ViewBuilder
    private var contributionsList: some View {
        if filteredContributions.isEmpty {
            EmptyState(
                icon: "arrow.down.to.line",
                title: "Переводов в цели не было",
                message: "Перевод в цель — это решение в день зарплаты, а не остаток в конце месяца. Пополните цель на вкладке «Цели».",
                actionTitle: "Перейти к целям",
                action: { bus.section = .goals }
            )
            .cardStyle()
        } else {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(filteredContributions) { item in
                    HStack(spacing: 12) {
                        let goal = store.data.goals.first(where: { $0.id == item.goalID })
                        Text(goal?.emoji ?? "🎯")
                            .font(.title3)
                            .frame(width: 34, height: 34)
                            .background(Circle().fill(Color(hex: goal?.colorHex ?? "#4F8DF7").opacity(0.15)))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(goal?.title ?? "Удалённая цель")
                                .font(.body)
                            Text(Fmt.dayShort.string(from: item.date) + (item.note.isEmpty ? "" : " · \(item.note)"))
                                .font(.caption)
                                .foregroundStyle(Palette.muted)
                        }
                        Spacer()
                        Text(Fmt.signedMoney(item.amount, code: currency, fraction: true))
                            .font(.system(size: 15, weight: .medium, design: .rounded))
                            .foregroundStyle(item.amount >= 0 ? Palette.accent : Palette.amber)
                    }
                    .padding(.vertical, 4)
                    .contextMenu {
                        Button("Удалить", role: .destructive) { store.deleteContribution(item) }
                    }
                    if item.id != filteredContributions.last?.id {
                        Divider().opacity(0.4)
                    }
                }
            }
            .cardStyle()
        }
    }
}

struct TransactionRow: View {
    var txn: Txn
    var currency: String
    var category: Category?

    var body: some View {
        HStack(spacing: 12) {
            Text(category?.emoji ?? "•")
                .font(.title3)
                .frame(width: 34, height: 34)
                .background(
                    Circle().fill(Palette.categoryColor(category?.kind ?? .flexible).opacity(0.14))
                )

            VStack(alignment: .leading, spacing: 2) {
                Text(category?.name ?? "Без категории")
                    .font(.body)
                if !txn.note.isEmpty {
                    Text(txn.note)
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 8)

            if txn.flow == .expense {
                Text((category?.kind ?? .flexible).title)
                    .font(.caption2)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(
                        Capsule().fill(Palette.categoryColor(category?.kind ?? .flexible).opacity(0.14))
                    )
                    .foregroundStyle(Palette.categoryColor(category?.kind ?? .flexible))
            }

            Text(Fmt.signedMoney(txn.signedAmount, code: currency, fraction: true))
                .font(.system(size: 15, weight: .medium, design: .rounded))
                .foregroundStyle(txn.flow == .income ? Palette.green : Palette.ink)
                .frame(minWidth: 90, alignment: .trailing)
        }
        .padding(.vertical, 3)
    }
}
