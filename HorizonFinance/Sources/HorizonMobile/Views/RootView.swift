import SwiftUI
import HorizonCore
import HorizonUI

/// Мобильная версия — вкладки вместо сайдбара, каждая в своём стеке навигации.
struct RootView: View {
    @EnvironmentObject private var store: Store
    @EnvironmentObject private var bus: UIBus

    var body: some View {
        TabView(selection: $bus.section) {
            ForEach(AppSection.allCases) { section in
                NavigationStack {
                    content(for: section)
                        .navigationTitle(section.title)
                }
                .tabItem {
                    Label(section.title, systemImage: section.icon)
                }
                .tag(section)
            }
        }
        .sheet(isPresented: $bus.showAddTransaction) {
            NavigationStack {
                TransactionEditor(mode: .create)
                    .environmentObject(store)
            }
        }
        .sheet(isPresented: $bus.showAddGoal) {
            NavigationStack {
                GoalEditor(mode: .create)
                    .environmentObject(store)
            }
        }
        .sheet(item: $bus.contributionTarget) { goal in
            NavigationStack {
                ContributionEditor(goal: goal)
                    .environmentObject(store)
            }
        }
    }

    @ViewBuilder
    private func content(for section: AppSection) -> some View {
        switch section {
        case .dashboard:
            DashboardView()
        case .transactions:
            TransactionsView()
        case .goals:
            GoalsView()
        case .analytics:
            AnalyticsView()
        case .settings:
            SettingsView()
        }
    }
}
