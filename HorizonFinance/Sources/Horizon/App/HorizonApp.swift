import SwiftUI
import AppKit

@main
struct HorizonApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var store = Store()
    @StateObject private var bus = UIBus()

    init() {
        // `swift run Horizon --self-check` — быстрая проверка расчётов без запуска окна.
        SelfCheck.runIfRequested()
    }

    var body: some Scene {
        WindowGroup("Горизонт") {
            RootView()
                .environmentObject(store)
                .environmentObject(bus)
                .frame(minWidth: 1060, minHeight: 680)
                .onDisappear { store.saveNow() }
        }
        .windowToolbarStyle(.unified)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Новая операция") { bus.showAddTransaction = true }
                    .keyboardShortcut("n", modifiers: [.command])
                Button("Новая цель") { bus.showAddGoal = true }
                    .keyboardShortcut("n", modifiers: [.command, .shift])
            }
            CommandGroup(replacing: .appSettings) {
                Button("Настройки…") { bus.section = .settings }
                    .keyboardShortcut(",", modifiers: [.command])
            }
            CommandGroup(after: .sidebar) {
                Divider()
                ForEach(Array(AppSection.allCases.enumerated()), id: \.element) { index, section in
                    Button(section.title) { bus.section = section }
                        .keyboardShortcut(KeyEquivalent(Character("\(index + 1)")), modifiers: [.command])
                }
            }
            CommandGroup(after: .saveItem) {
                Button("Сохранить сейчас") { store.saveNow() }
                    .keyboardShortcut("s", modifiers: [.command])
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Нужно, чтобы приложение вело себя как обычное оконное даже при запуске через `swift run`.
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}
