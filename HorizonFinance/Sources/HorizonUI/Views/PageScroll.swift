import SwiftUI
import HorizonCore

/// Общая обёртка страницы: заголовок, отступы, прокрутка.
public struct PageScroll<Content: View>: View {
    @ViewBuilder public var content: Content

    public init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    public var body: some View {
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
public struct BackgroundWash: View {
    public init() {}

    public var body: some View {
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
        .background(windowBackground.ignoresSafeArea())
    }

    /// Фон окна: на Mac — системный цвет окна, на iOS — системная групповая подложка.
    private var windowBackground: Color {
        #if os(macOS)
        Color(nsColor: .windowBackgroundColor)
        #else
        Color(uiColor: .systemGroupedBackground)
        #endif
    }
}
