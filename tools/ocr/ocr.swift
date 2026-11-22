// macOS Vision çatısıyla görseldeki yazıları okur (Türkçe dahil, çevrimdışı).
// Kullanım: ocr <görsel yolu>   → her satıra: güven<TAB>metin
import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1 else {
    FileHandle.standardError.write("kullanım: ocr <görsel>\n".data(using: .utf8)!)
    exit(2)
}
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let img = NSImage(contentsOf: url),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("görsel açılamadı\n".data(using: .utf8)!)
    exit(1)
}

let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = true
req.automaticallyDetectsLanguage = true
// Desteklenen dillerden geniş bir öncelik listesi; Vision kendi tanıdıklarını kullanır.
let wanted = ["tr-TR", "en-US", "de-DE", "fr-FR", "it-IT", "es-ES", "pt-BR", "ru-RU", "uk-UA", "ar-SA", "zh-Hans", "ja-JP", "ko-KR"]
if let supported = try? req.supportedRecognitionLanguages() {
    req.recognitionLanguages = wanted.filter { supported.contains($0) }
}

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do {
    try handler.perform([req])
} catch {
    FileHandle.standardError.write("ocr hatası: \(error)\n".data(using: .utf8)!)
    exit(1)
}
for obs in req.results ?? [] {
    if let top = obs.topCandidates(1).first {
        print(String(format: "%.2f", top.confidence) + "\t" + top.string)
    }
}
