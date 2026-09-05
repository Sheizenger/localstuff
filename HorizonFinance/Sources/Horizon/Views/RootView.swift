import SwiftUI

struct RootView: View {
    @EnvironmentObject private var store: Store
    @EnvironmentObject private var bus: UIBus

    private var selection: Binding<AppSection?> {
        Binding(
            get: { bus.section },
            set: { newValue in if let newValue = newValue { bus.section = newValue } }
        )
    }

    var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            detail
                .navigationTitle(bus.section.title)
                .navigationSubtitle(bus.section.subtitle)
                .toolbar { toolbarContent }
        }
        .sheet(isPresented: $bus.showAddTransaction) {
            TransactionEditor(mode: .create)
                .environmentObject(store)
        }
        .sheet(isPresented: $bus.showAddGoal) {
            GoalEditor(mode: .create)
                .environmentObject(store)
        }
        .onAppear {
            // Аренда и подписки известны заранее — создаём их сами, а не ждём ручного ввода.
            store.applyRecurringRules()
        }
        .sheet(isPresented: $bus.showReceiptImport) {
            ReceiptImportView()
                .environmentObject(store)
        }
        .sheet(isPresented: $bus.showStatementImport) {
            StatementImportView()
                .environmentObject(store)
        }
        .sheet(item: $bus.contributionTarget) { goal in
            ContributionEditor(goal: goal)
                .environmentObject(store)
        }
    }

    // MARK: Боковая панель

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            List(selection: selection) {
                Section("Разделы") {
                    ForEach(AppSection.allCases) { section in
                        Label(section.title, systemImage: section.icon)
                            .tag(section)
                    }
                }
            }
            .listStyle(.sidebar)

            Divider()
            sidebarFooter
        }
        .navigationSplitViewColumnWidth(min: 210, ideal: 226, max: 280)
    }

    /// Три живых показателя внизу боковой панели: сколько всего есть, что вышло за месяц
    /// и сколько осталось свободных денег. Пересчитываются при любом изменении данных.
    private var sidebarFooter: some View {
        let analytics = store.analytics
        let month = analytics.thisMonth
        let status = analytics.budgetStatus
        let hasLimit = store.data.profile.flexibleLimit > 0

        return VStack(alignment: .leading, spacing: 12) {
            footerBlock(
                title: "Капитал",
                value: Fmt.money(analytics.totalCapital, code: store.currency),
                caption: "свободные \(Fmt.money(analytics.freeCash, code: store.currency)) · в целях \(Fmt.money(analytics.totalInGoals, code: store.currency))",
                color: Palette.ink,
                section: .goals,
                help: "Всё, что у вас есть: свободные деньги плюс накопленное по целям"
            )

            Divider().opacity(0.35)

            footerBlock(
                title: "Баланс месяца",
                value: Fmt.signedMoney(month.net, code: store.currency),
                caption: "доход \(Fmt.money(month.income, code: store.currency)) · расходы \(Fmt.money(month.expense, code: store.currency))",
                color: month.net >= 0 ? Palette.green : Palette.red,
                section: .transactions,
                help: "Доход минус все расходы за \(analytics.currentMonth.listTitle)"
            )

            Divider().opacity(0.35)

            freeAllowanceBlock(status: status, hasLimit: hasLimit)

            Text("Темп накоплений: \(Fmt.money(analytics.pace.value, code: store.currency))/мес.")
                .font(.caption2)
                .foregroundStyle(Palette.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
    }

    private func footerBlock(
        title: String,
        value: String,
        caption: String,
        color: Color,
        section: AppSection,
        help: String
    ) -> some View {
        Button {
            bus.section = section
        } label: {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                Text(value)
                    .font(.system(size: 19, weight: .semibold, design: .rounded))
                    .foregroundStyle(color)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                Text(caption)
                    .font(.caption2)
                    .foregroundStyle(Palette.muted)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(help)
    }

    @ViewBuilder
    private func freeAllowanceBlock(status: BudgetStatus, hasLimit: Bool) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Text("Запас свободных")
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                Spacer(minLength: 4)
                if hasLimit {
                    Circle()
                        .fill(status.zone.color)
                        .frame(width: 7, height: 7)
                    Text(status.zone.title)
                        .font(.caption2)
                        .foregroundStyle(status.zone.color)
                }
            }

            if hasLimit {
                Text("\(Fmt.money(max(status.remaining, 0), code: store.currency)) из \(Fmt.money(status.limit, code: store.currency))")
                    .font(.system(size: 17, weight: .semibold, design: .rounded))
                    .foregroundStyle(status.remaining >= 0 ? Palette.ink : Palette.red)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                MeterBar(
                    value: status.spent,
                    limit: status.limit,
                    zone: status.zone,
                    projection: status.projected,
                    height: 7
                )
                Text("осталось \(Fmt.daysWord(status.daysLeft)) · по \(Fmt.money(status.dailyAllowance, code: store.currency)) в день")
                    .font(.caption2)
                    .foregroundStyle(Palette.muted)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            } else {
                Text("лимит не задан")
                    .font(.callout)
                    .foregroundStyle(Palette.muted)
                Button("Задать в настройках") { bus.section = .settings }
                    .buttonStyle(.link)
                    .font(.caption2)
            }
        }
        .help("Лимит свободных трат на месяц и сколько от него осталось")
    }

    // MARK: Контент

    @ViewBuilder
    private var detail: some View {
        switch bus.section {
        case .dashboard:
            DashboardView()
        case .transactions:
            TransactionsView()
        case .goals:
            GoalsView()
        case .basket:
            BasketView()
        case .analytics:
            AnalyticsView()
        case .settings:
            SettingsView()
        }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .primaryAction) {
            Button {
                bus.showAddGoal = true
            } label: {
                Label("Новая цель", systemImage: "target")
            }
            .help("Добавить цель накопления (⇧⌘N)")
        }
        ToolbarItem(placement: .primaryAction) {
            Button {
                bus.showReceiptImport = true
            } label: {
                Label("Чек из магазина", systemImage: "doc.viewfinder")
            }
            .help("Распознать чек из снимка или PDF (⌘I)")
        }
        ToolbarItem(placement: .primaryAction) {
            Button {
                bus.showAddTransaction = true
            } label: {
                Label("Новая операция", systemImage: "plus")
            }
            .help("Добавить доход или расход (⌘N)")
        }
    }
}

/// Общая обёртка страницы: заголовок, отступы, прокрутка.
struct PageScroll<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Metrics.gap) {
                content
            }
            .padding(20)
            .frame(maxWidth: 1180, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(BackgroundWash())
    }
}

/// Мягкая подложка, чтобы карточки читались как слои, а не как плоский список.
struct BackgroundWash: View {
    var body: some View {
        LinearGradient(
            colors: [
                Palette.accent.opacity(0.10),
                Color.clear,
                Palette.violet.opacity(0.07)
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
        .ignoresSafeArea()
        .background(Color(nsColor: .windowBackgroundColor).ignoresSafeArea())
    }
}
