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

    private var sidebarFooter: some View {
        let analytics = store.analytics
        let status = analytics.budgetStatus
        return VStack(alignment: .leading, spacing: 10) {
            Text("Капитал")
                .font(.caption)
                .foregroundStyle(Palette.muted)
            Text(Fmt.money(analytics.totalCapital, code: store.currency))
                .font(.system(size: 19, weight: .semibold, design: .rounded))
            HStack(spacing: 6) {
                ZoneBadge(zone: status.zone)
            }
            Text("Темп: \(Fmt.money(analytics.pace.value, code: store.currency))/мес.")
                .font(.caption2)
                .foregroundStyle(Palette.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
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
