import Foundation
import Vision
import AppKit
import PDFKit

/// Что удалось прочитать с картинки или PDF до разбора смысла.
struct ScannedDocument {
    var lines: [String] = []
    /// Содержимое QR и штрихкодов: у испанских чеков это TicketBAI или Verifactu.
    var codes: [String] = []
    var usedOCR: Bool = true
}

enum ReceiptScanner {

    enum ScanError: LocalizedError {
        case unreadableFile
        case noText

        var errorDescription: String? {
            switch self {
            case .unreadableFile: return "Не удалось открыть файл — нужен снимок, фото или PDF чека."
            case .noText: return "На изображении не нашлось текста. Попробуйте снимок покрупнее и без бликов."
            }
        }
    }

    // MARK: Точки входа

    static func scan(url: URL) throws -> ScannedDocument {
        if url.pathExtension.lowercased() == "pdf" {
            if let document = scanPDFText(url: url) { return document }
        }
        guard let image = NSImage(contentsOf: url) else { throw ScanError.unreadableFile }
        return try scan(image: image)
    }

    static func scan(image: NSImage) throws -> ScannedDocument {
        guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            throw ScanError.unreadableFile
        }
        return try scan(cgImage: cgImage)
    }

    /// Текстовый слой PDF лучше любого распознавания — если он есть, берём его.
    static func scanPDFText(url: URL) -> ScannedDocument? {
        guard let document = PDFDocument(url: url), let text = document.string else { return nil }
        let lines = text
            .components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        guard lines.count >= 5 else { return nil }
        return ScannedDocument(lines: lines, codes: [], usedOCR: false)
    }

    // MARK: Распознавание

    static func scan(cgImage: CGImage) throws -> ScannedDocument {
        let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])

        let textRequest = VNRecognizeTextRequest()
        textRequest.recognitionLevel = .accurate
        // Коррекция по словарю портит сокращения вроде «LECHE ENT SEMI».
        textRequest.usesLanguageCorrection = false
        textRequest.recognitionLanguages = ["es-ES", "en-US"]

        let codeRequest = VNDetectBarcodesRequest()

        try handler.perform([textRequest, codeRequest])

        var fragments: [Fragment] = []
        let observations = (textRequest.results ?? []).compactMap { $0 as? VNRecognizedTextObservation }
        for observation in observations {
            guard let candidate = observation.topCandidates(1).first else { continue }
            fragments.append(Fragment(text: candidate.string, box: observation.boundingBox))
        }

        var codes: [String] = []
        let barcodes = (codeRequest.results ?? []).compactMap { $0 as? VNBarcodeObservation }
        for barcode in barcodes {
            if let payload = barcode.payloadStringValue, !payload.isEmpty {
                codes.append(payload)
            }
        }

        let lines = assembleLines(from: fragments)
        guard !lines.isEmpty else { throw ScanError.noText }
        return ScannedDocument(lines: lines, codes: codes, usedOCR: true)
    }

    // MARK: Сборка строк

    private struct Fragment {
        let text: String
        /// Нормализованный прямоугольник Vision: начало координат внизу слева.
        let box: CGRect
    }

    /// Vision возвращает куски текста, а не строки: название слева и цена справа —
    /// это два разных наблюдения. Собираем их обратно по вертикали.
    private static func assembleLines(from fragments: [Fragment]) -> [String] {
        guard !fragments.isEmpty else { return [] }

        let averageHeight = fragments.reduce(0.0) { $0 + $1.box.height } / Double(fragments.count)
        let tolerance = max(averageHeight * 0.6, 0.004)

        let sorted = fragments.sorted { $0.box.midY > $1.box.midY }
        var groups: [[Fragment]] = []

        for fragment in sorted {
            if var last = groups.last,
               let reference = last.first,
               abs(reference.box.midY - fragment.box.midY) <= tolerance {
                last.append(fragment)
                groups[groups.count - 1] = last
            } else {
                groups.append([fragment])
            }
        }

        return groups.map { group in
            group
                .sorted { $0.box.minX < $1.box.minX }
                .map { $0.text }
                .joined(separator: "  ")
                .trimmingCharacters(in: .whitespaces)
        }
        .filter { !$0.isEmpty }
    }
}
