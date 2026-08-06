// GovDocLetter.cs — 信函格式模板（只读参考，不要直接修改）
// 适用于：函（商洽函、询问函、答复函、催办函、邀请函等）
// 与标准红头文件的区别：
//   - 发文机关名称后加"函"字，不加"文件"
//   - 发文字号置于武文线（红色分隔线）下方居左
//   - 无份号、密级、紧急程度
//   - 版记更简洁
//
// 用法：agent 在 cwd 下创建 Program.cs，参考本文件编写，然后执行构建

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

string outputFile = args.Length > 0 ? args[0] : "letter.docx";

// ── 函件元数据 ──
string govOrg = "\u4E0A\u6D77\u5E02\u6C11\u653F\u5C40";      // 上海市民政局
string docNum = "\u6CAA\u6C11\u51FD\u30142025\u301512\u53F7";  // 沪民函〔2025〕12号
string docTitle = "\u5173\u4E8E\u534F\u52A9\u6838\u67E5\u7279\u56F0\u4EBA\u5458\u8D22\u4EA7\u72B6\u51B5\u7684\u51FD";  // 关于协助核查特困人员财产状况的函
string sendTo = "\u4E0A\u6D77\u5E02\u89C4\u5212\u548C\u81EA\u7136\u8D44\u6E90\u5C40";  // 上海市规划和自然资源局
string docDate = "2025\u5E742\u670812\u65E5";
string ccOrgs = "\u5E02\u8D22\u653F\u5C40";

const string GOV_RED = "C81414";
const string BLACK = "000000";
const uint A4W = 11906;
const uint A4H = 16838;
const int MTop = 2098;
const int MBot = 1984;
const int MLeft = 1588;
const int MRight = 1474;

using var doc = WordprocessingDocument.Create(outputFile, WordprocessingDocumentType.Document);
var mainPart = doc.AddMainDocumentPart();
mainPart.Document = new Document();
var body = new Body();

AddStyles(mainPart);

// ══════════════════════════════════════════════
// 版头：机关名称 + "函" 字（信函格式特有）
// ══════════════════════════════════════════════
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { Before = "800", After = "100" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FZXiaoBiaoSong-B05", HighAnsi = "FZXiaoBiaoSong-B05", EastAsia = "FZXiaoBiaoSong-B05" },
            new FontSize { Val = "44" }, new FontSizeComplexScript { Val = "44" },
            new Color { Val = GOV_RED }
        ),
        new Text(govOrg + "\u51FD")  // 上海市民政局函
    )
));

// ── 红色武文线（信函用细线） ──
body.Append(new Paragraph(
    new ParagraphProperties(
        new ParagraphBorders(
            new BottomBorder { Val = BorderValues.Single, Size = 4, Color = GOV_RED, Space = 1 }
        ),
        new SpacingBetweenLines { Before = "0", After = "0" }
    )
));

// ── 发文字号（信函格式：居左） ──
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Left },
        new SpacingBetweenLines { Before = "100", After = "200" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
        ),
        new Text(docNum)
    )
));

// ══════════════════════════════════════════════
// 标题
// ══════════════════════════════════════════════
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { Before = "200", After = "300", Line = "570", LineRule = LineSpacingRuleValues.Exact }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FZXiaoBiaoSong-B05", HighAnsi = "FZXiaoBiaoSong-B05", EastAsia = "FZXiaoBiaoSong-B05" },
            new FontSize { Val = "44" }, new FontSizeComplexScript { Val = "44" }
        ),
        new Text(docTitle)
    )
));

// ══════════════════════════════════════════════
// 主送机关
// ══════════════════════════════════════════════
body.Append(CreateBodyPara(sendTo + "\uFF1A", bold: false, indent: false));

// ══════════════════════════════════════════════
// 正文
// ══════════════════════════════════════════════
body.Append(CreateBodyPara(
    "\u6839\u636E\u300A\u793E\u4F1A\u6551\u52A9\u6682\u884C\u529E\u6CD5\u300B" +
    "\uFF08\u56FD\u52A1\u9662\u4EE4\u7B2C649\u53F7\uFF09\u7B2C\u4E09\u5341\u4E8C\u6761\u89C4\u5B9A\uFF0C" +
    "\u7279\u56F0\u4EBA\u5458\u8D22\u4EA7\u72B6\u51B5\u6838\u67E5\u9700\u8981\u591A\u90E8\u95E8\u534F\u52A9\u3002" +
    "\u73B0\u5C31\u6709\u5173\u4E8B\u9879\u51FD\u544A\u5982\u4E0B\uFF1A"
));

body.Append(CreateBodyPara(
    "\u4E00\u3001\u8BF7\u534F\u52A9\u67E5\u8BE2\u4EE5\u4E0B\u4EBA\u5458\u540D\u4E0B\u7684\u4E0D\u52A8\u4EA7\u767B\u8BB0\u4FE1\u606F\uFF1A" +
    "\u738B\u67D0\uFF08\u8EAB\u4EFD\u8BC1\u53F7\uFF1A310XXXXXXXXXXXXX01\uFF09\u3002",
    bold: false, indent: true
));

body.Append(CreateBodyPara(
    "\u4E8C\u3001\u8BF7\u4E8E\u6536\u5230\u672C\u51FD\u540E5\u4E2A\u5DE5\u4F5C\u65E5\u5185\u5C06\u67E5\u8BE2\u7ED3\u679C\u53CD\u9988\u81F3\u6211\u5C40\u793E\u4F1A\u6551\u52A9\u5904\u3002",
    bold: false, indent: true
));

body.Append(CreateBodyPara(
    "\u5982\u6709\u7591\u95EE\uFF0C\u8BF7\u4E0E\u6211\u5C40\u793E\u4F1A\u6551\u52A9\u5904\u8054\u7CFB\uFF0C" +
    "\u8054\u7CFB\u7535\u8BDD\uFF1A021-XXXXXXXX\u3002"
));

// ══════════════════════════════════════════════
// 落款
// ══════════════════════════════════════════════
body.Append(new Paragraph(new ParagraphProperties(new SpacingBetweenLines { Before = "600" })));

body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Right },
        new SpacingBetweenLines { After = "100", Line = "570", LineRule = LineSpacingRuleValues.Exact }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
        ),
        new Text(govOrg)
    )
));

body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Right },
        new SpacingBetweenLines { After = "200", Line = "570", LineRule = LineSpacingRuleValues.Exact }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
        ),
        new Text(docDate)
    )
));

// ══════════════════════════════════════════════
// 版记（信函格式简化版）
// ══════════════════════════════════════════════
body.Append(new Paragraph(
    new ParagraphProperties(
        new ParagraphBorders(
            new TopBorder { Val = BorderValues.Single, Size = 4, Color = GOV_RED, Space = 1 }
        ),
        new SpacingBetweenLines { Before = "600", After = "0" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }
        ),
        new Text("\u6284\u9001\uFF1A" + ccOrgs + "\u3002")
    )
));

body.Append(new Paragraph(
    new ParagraphProperties(
        new ParagraphBorders(
            new BottomBorder { Val = BorderValues.Single, Size = 4, Color = GOV_RED, Space = 1 }
        ),
        new SpacingBetweenLines { Before = "0", After = "0" }
    )
));

// ══════════════════════════════════════════════
// 页脚 + 页面设置
// ══════════════════════════════════════════════
var footerPart = mainPart.AddNewPart<FooterPart>();
var footerId = mainPart.GetIdOfPart(footerPart);

var footerPara = new Paragraph(
    new ParagraphProperties(new Justification { Val = JustificationValues.Center })
);
footerPara.Append(new Run(
    new RunProperties(
        new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
        new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }
    ),
    new Text("\u2014 ") { Space = SpaceProcessingModeValues.Preserve }
));
footerPara.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }));
footerPara.Append(new Run(new FieldCode(" PAGE ")));
footerPara.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }));
footerPara.Append(new Run(new Text("1")));
footerPara.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.End }));
footerPara.Append(new Run(
    new RunProperties(
        new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
        new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }
    ),
    new Text(" \u2014") { Space = SpaceProcessingModeValues.Preserve }
));
footerPart.Footer = new Footer(footerPara);

body.Append(new SectionProperties(
    new FooterReference { Type = HeaderFooterValues.Default, Id = footerId },
    new PageSize { Width = A4W, Height = A4H },
    new PageMargin { Top = MTop, Bottom = MBot, Left = (uint)MLeft, Right = (uint)MRight, Header = 720, Footer = 720 }
));

mainPart.Document.Append(body);
doc.Save();
Console.WriteLine($"\u2705 \u51FD\u4EF6\u751F\u6210\u5B8C\u6210\uFF1A{outputFile}");

// ══════════════════════════════════════════════
// 辅助方法
// ══════════════════════════════════════════════

static Paragraph CreateBodyPara(string text, bool bold = false, bool indent = true)
{
    var pProps = new ParagraphProperties(
        new Justification { Val = JustificationValues.Both },
        new SpacingBetweenLines { Line = "570", LineRule = LineSpacingRuleValues.Exact, After = "0" }
    );
    if (indent) pProps.Append(new Indentation { FirstLine = "640" });
    var rProps = new RunProperties(
        new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
        new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
    );
    if (bold) rProps.Append(new Bold());
    return new Paragraph(pProps, new Run(rProps, new Text(text)));
}

static void AddStyles(MainDocumentPart mainPart)
{
    var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
    stylesPart.Styles = new Styles();

    stylesPart.Styles.Append(new Style(
        new StyleName { Val = "Normal" },
        new StyleParagraphProperties(
            new SpacingBetweenLines { Line = "570", LineRule = LineSpacingRuleValues.Exact, After = "0" },
            new Indentation { FirstLine = "640" }
        ),
        new StyleRunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" },
            new Color { Val = "000000" }
        )
    ) { Type = StyleValues.Paragraph, StyleId = "Normal", Default = true });
}
