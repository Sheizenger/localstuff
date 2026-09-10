import SwiftUI
import HorizonCore

@main
struct HorizonMobileApp: App {
    @StateObject private var store = Store()
    @StateObject private var bus = UIBus()

    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(store)
                .environmentObject(bus)
        }
        .onChange(of: scenePhase) { newPhase in
            // На iOS `.onDisappear` ненадёжен (система может просто заморозить процесс),
            // поэтому сохраняем явно при уходе в фон.
            if newPhase == .background {
                store.saveNow()
            }
        }
    }
}
