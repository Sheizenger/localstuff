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
    @State private var expandedReceiptID: UUID? = nil
    @State private var filter: Filter = .all

    /// Быстрый фильтр списка — включается нажатием на плитку итогов.
    enum Filter: String, CaseIterable, Identifiable {
        case all
        case income
        case essential
        case flexible

        var id: String { rawValue }

        var title: String {
            switch self {
            case .all: return "все операции"
            case .income: return "доходы"
            case .essential: return "обязательные расходы"
            case .flexible: return "свободные траты"
            }
        }
    }

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

            filterChip

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
                bus.showReceiptImport = true
            } label: {
                Label("Чек", systemImage: "doc.viewfinder")
            }
            .help("Распознать чек из снимка или PDF (⌘I)")

            Button {
                bus.showStatementImport = true
            } label: {
                Label("Выписка", systemImage: "tablecells")
            }
            .help("Импортировать выписку банка из CSV (⇧⌘I)")

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
        let limit = store.data.profile.flexibleLimit
        let flexibleValue = limit > 0
            ? "\(Fmt.money(stats.flexible, code: currency)) из \(Fmt.money(limit, code: currency))"
            : Fmt.money(stats.flexible, code: currency)

        return HStack(spacing: 12) {
            summaryTile(
                title: "Доход",
                value: Fmt.money(stats.income, code: currency),
                color: Palette.green,
                filter: .income,
                help: "Все поступления за месяц. Нажмите, чтобы оставить в списке только доходы."
            )
            summaryTile(
                title: "Обязательные",
                value: Fmt.money(stats.essential, code: currency),
                color: Palette.teal,
                filter: .essential,
                help: "Аренда, счета, продукты, транспорт — лимит месяца они не трогают."
            )
            summaryTile(
                title: "Свободные",
                value: flexibleValue,
                color: Palette.violet,
                filter: .flexible,
                help: "Кафе, покупки, поездки — именно они съедают месячный лимит."
            )
            summaryTile(
                title: "Осталось",
                value: Fmt.signedMoney(stats.net, code: currency),
                color: stats.net >= 0 ? Palette.green : Palette.red,
                filter: nil,
                help: "Доход минус все расходы за месяц — это и есть темп накоплений."
            )
            summaryTile(
                title: "В цели",
                value: Fmt.money(stats.moved, code: currency),
                color: Palette.accent,
                filter: nil,
                help: "Сколько за месяц переведено в цели."
            )
        }
    }

    private func summaryTile(
        title: String,
        value: String,
        color: Color,
        filter target: Filter?,
        help: String
    ) -> some View {
        let isActive = target != nil && filter == target
        return Button {
            guard let target = target else { return }
            filter = (filter == target) ? .all : target
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                Text(value)
                    .font(.system(size: 17, weight: .semibold, design: .rounded))
                    .foregroundStyle(color)
                    .lineLimit(1)
                    .minimumScaleFactor(0.55)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(.regularMaterial)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(isActive ? color : Color.clear, lineWidth: 1.5)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(help)
    }

    @ViewBuilder
    private var filterChip: some View {
        if filter != .all {
            HStack(spacing: 8) {
                Label("Показаны только: \(filter.title)", systemImage: "line.3.horizontal.decrease.circle.fill")
                    .font(.caption)
                    .foregroundStyle(Palette.accent)
                Button {
                    filter = .all
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 11))
                }
                .buttonStyle(.plain)
                .foregroundStyle(Palette.muted)
                .help("Показать все операции")
                Spacer()
            }
        }
    }

    /// «Сегодня» и «Вчера» читаются быстрее, чем дата.
    private func dayTitle(_ date: Date) -> String {
        if Cal.ru.isDateInToday(date) {
            return "Сегодня, " + Fmt.daySimple.string(from: date)
        }
        if Cal.ru.isDateInYesterday(date) {
            return "Вчера, " + Fmt.daySimple.string(from: date)
        }
        return Fmt.dayLong.string(from: date).capitalizedFirst
    }

    // MARK: Операции

    private var filteredTxns: [Txn] {
        let analytics = store.analytics
        let text = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return store.data.transactions
            .filter { MonthKey(date: $0.date) == month }
            .filter { txn in
                switch filter {
                case .all:
                    return true
                case .income:
                    return txn.flow == .income
                case .essential:
                    return txn.flow == .expense && analytics.kind(of: txn) == .essential
                case .flexible:
                    return txn.flow == .expense && analytics.kind(of: txn) == .flexible
                }
            }
            .filter { txn in
                guard !text.isEmpty else { return true }
                let categoryName = analytics.category(for: txn)?.name.lowercased() ?? ""
                let merchant = txn.merchant.lowercased()
                return txn.note.lowercased().contains(text)
                    || categoryName.contains(text)
                    || merchant.contains(text)
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
            if filter == .all && query.isEmpty {
                EmptyState(
                    icon: "tray",
                    title: "В этом месяце пусто",
                    message: "Добавьте первую операцию — доход, аренду, продукты или кофе. Прогноз пересчитается автоматически.",
                    actionTitle: "Добавить операцию",
                    action: { bus.showAddTransaction = true }
                )
                .cardStyle()
            } else {
                EmptyState(
                    icon: "line.3.horizontal.decrease.circle",
                    title: "Ничего не подошло",
                    message: "Под текущий отбор операций в этом месяце нет. Сбросьте фильтр или поиск.",
                    actionTitle: "Показать все",
                    action: {
                        filter = .all
                        query = ""
                    }
                )
                .cardStyle()
            }
        } else {
            ForEach(groupedTxns) { group in
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(dayTitle(group.date))
                            .font(.subheadline.weight(.semibold))
                        Spacer()
                        Text(Fmt.signedMoney(group.items.reduce(0.0) { $0 + $1.signedAmount }, code: currency, fraction: true))
                            .font(.subheadline)
                            .foregroundStyle(Palette.muted)
                    }
                    ForEach(group.items) { txn in
                        VStack(alignment: .leading, spacing: 6) {
                            TransactionRow(txn: txn, currency: currency, category: store.analytics.category(for: txn))
                                .contentShape(Rectangle())
                                .onTapGesture { editingTxn = txn }
                                .contextMenu {
                                    Button("Изменить") { editingTxn = txn }
                                    Button("Удалить", role: .destructive) { store.deleteTransaction(txn) }
                                }

                            if txn.hasReceipt {
                                Button {
                                    expandedReceiptID = expandedReceiptID == txn.id ? nil : txn.id
                                } label: {
                                    HStack(spacing: 5) {
                                        Image(systemName: expandedReceiptID == txn.id ? "chevron.down" : "chevron.right")
                                            .font(.system(size: 9, weight: .bold))
                                        Image(systemName: "doc.text")
                                            .font(.system(size: 10))
                                        Text("чек, позиций: \(txn.receiptLines.count)")
                                            .font(.caption2)
                                    }
                                    .foregroundStyle(Palette.teal)
                                }
                                .buttonStyle(.plain)
                                .padding(.leading, 46)

                                if expandedReceiptID == txn.id {
                                    ReceiptBreakdownView(lines: txn.receiptLines, currency: currency)
                                        .padding(.leading, 46)
                                        .padding(.bottom, 4)
                                }
                            }
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

/// Что лежит внутри операции, пришедшей из чека: суммы по категориям и сами позиции.
struct ReceiptBreakdownView: View {
    var lines: [ReceiptLine]
    var currency: String

    private struct CategorySum: Identifiable {
        let category: BasketCategory
        let amount: Double
        var id: String { category.rawValue }
    }

    private var groups: [CategorySum] {
        BasketCategory.allCases
            .compactMap { category in
                let sum = lines.filter { $0.category == category }.reduce(0.0) { $0 + $1.amount }
                return abs(sum) > 0.001 ? CategorySum(category: category, amount: sum) : nil
            }
            .sorted { $0.amount > $1.amount }
    }

    private var total: Double {
        max(abs(lines.reduce(0.0) { $0 + $1.amount }), 0.01)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(groups) { group in
                HStack(spacing: 8) {
                    Text("\(group.category.emoji) \(group.category.title)")
                        .font(.caption)
                        .frame(width: 160, alignment: .leading)
                    GeometryReader { geo in
                        Capsule()
                            .fill(Palette.basketColor(group.category).opacity(0.7))
                            .frame(width: max(geo.size.width * CGFloat(abs(group.amount) / total), 3))
                    }
                    .frame(height: 7)
                    Text(Fmt.money(group.amount, code: currency, fraction: true))
                        .font(.caption.monospacedDigit())
                        .frame(width: 74, alignment: .trailing)
                }
            }

            Divider().opacity(0.3)

            ForEach(lines) { line in
                HStack(spacing: 8) {
                    Circle()
                        .fill(Palette.basketColor(line.category))
                        .frame(width: 5, height: 5)
                    Text(line.name)
                        .font(.caption2)
                        .lineLimit(1)
                    Spacer(minLength: 8)
                    if line.quantity > 1.001 || line.quantity < 0.999 {
                        Text(String(format: "×%.3g", line.quantity))
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(Palette.muted)
                    }
                    Text(Fmt.money(line.amount, code: currency, fraction: true))
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(line.isDiscount ? Palette.green : Palette.muted)
                        .frame(width: 66, alignment: .trailing)
                }
            }
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color.primary.opacity(0.035))
        )
    }
}
