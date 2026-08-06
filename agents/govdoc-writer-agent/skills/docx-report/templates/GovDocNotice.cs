// GovDocExample.cs — 红头文件完整示例
// 遵循 GB/T 9704-2012《党政机关公文格式》
// 用法：复制到 Program.cs，修改内容后 ./scripts/build 构建
//
// 结构：版头 → 标题 → 主送 → 正文 → 落款 → 版记 → 政策索引表

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

string outputFile = args.Length > 0 ? args[0] : "output.docx";

// ── 公文元数据（按需修改） ──
string govOrg = "上海市民政局";
string govDocNum = "\u6CAA\u6C11\u89C4\u30142025\u30151\u53F7";  // 沪民规〔2025〕1号
string docTitle = "\u5173\u4E8E\u52A0\u5F3A\u793E\u4F1A\u6551\u52A9\u4E3B\u52A8\u53D1\u73B0\u673A\u5236\u7684\u901A\u77E5";
string sendTo = "\u5404\u533A\u6C11\u653F\u5C40";  // 各区民政局
string docDate = "2025\u5E742\u670812\u65E5";       // 2025年2月12日
string ccOrgs = "\u5E02\u8D22\u653F\u5C40\u3001\u5E02\u4EBA\u793E\u5C40";  // 市财政局、市人社局

// ── 颜色常量 ──
const string GOV_RED = "C81414";
const string BLACK = "000000";

// ── 尺寸常量（Twips） ──
const uint A4W = 11906;   // 210mm
const uint A4H = 16838;   // 297mm
const int MTop = 2098;    // 37mm
const int MBot = 1984;    // 35mm
const int MLeft = 1588;   // 28mm
const int MRight = 1474;  // 26mm

using var doc = WordprocessingDocument.Create(outputFile, WordprocessingDocumentType.Document);
var mainPart = doc.AddMainDocumentPart();
mainPart.Document = new Document();
var body = new Body();

// ══════════════════════════════════════════════
// 样式定义
// ══════════════════════════════════════════════
AddStyles(mainPart);

// ══════════════════════════════════════════════
// 版头：机关名称（红色大字）
// ══════════════════════════════════════════════
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { Before = "1200", After = "100" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FZXiaoBiaoSong-B05", HighAnsi = "FZXiaoBiaoSong-B05", EastAsia = "FZXiaoBiaoSong-B05" },
            new FontSize { Val = "44" },           // 二号 = 22pt = 44半磅
            new FontSizeComplexScript { Val = "44" },
            new Color { Val = GOV_RED }
        ),
        new Text(govOrg)
    )
));

// ── 红色分隔线 ──
body.Append(new Paragraph(
    new ParagraphProperties(
        new ParagraphBorders(
            new BottomBorder { Val = BorderValues.Single, Size = 8, Color = GOV_RED, Space = 1 }
        ),
        new SpacingBetweenLines { Before = "0", After = "0" }
    )
));

// ── 发文字号 ──
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { Before = "100", After = "200" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" },           // 三号 = 16pt = 32半磅
            new FontSizeComplexScript { Val = "32" }
        ),
        new Text(govDocNum)
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
            new FontSize { Val = "44" },
            new FontSizeComplexScript { Val = "44" }
        ),
        new Text(docTitle)
    )
));

// ══════════════════════════════════════════════
// 主送机关
// ══════════════════════════════════════════════
body.Append(CreateBodyPara(sendTo + "\uFF1A", bold: false, indent: false));  // 各区民政局：

// ══════════════════════════════════════════════
// 正文
// ══════════════════════════════════════════════

// 引言段落
body.Append(CreateBodyPara(
    "\u4E3A\u8D2F\u5F7B\u843D\u5B9E\u300A\u793E\u4F1A\u6551\u52A9\u6682\u884C\u529E\u6CD5\u300B" +
    "\uFF08\u56FD\u52A1\u9662\u4EE4\u7B2C649\u53F7\uFF09\u548C\u300A\u4E0A\u6D77\u5E02\u793E\u4F1A" +
    "\u6551\u52A9\u6761\u4F8B\u300B\uFF0C\u8FDB\u4E00\u6B65\u52A0\u5F3A\u672C\u5E02\u793E\u4F1A" +
    "\u6551\u52A9\u5DE5\u4F5C\uFF0C\u73B0\u5C31\u6709\u5173\u4E8B\u9879\u901A\u77E5\u5982\u4E0B\uFF1A"
));

// 一级标题
body.Append(CreateHeading1("\u4E00\u3001\u603B\u4F53\u8981\u6C42"));  // 一、总体要求

body.Append(CreateBodyPara(
    "\u575A\u6301\u4EE5\u4EBA\u6C11\u4E3A\u4E2D\u5FC3\u7684\u53D1\u5C55\u601D\u60F3\uFF0C" +
    "\u6309\u7167\u515C\u5E95\u7EBF\u3001\u7EC7\u5BC6\u7F51\u3001\u5EFA\u673A\u5236\u7684\u8981\u6C42\uFF0C" +
    "\u5B8C\u5584\u793E\u4F1A\u6551\u52A9\u5236\u5EA6\u4F53\u7CFB\uFF0C" +
    "\u5207\u5B9E\u4FDD\u969C\u56F0\u96BE\u7FA4\u4F17\u57FA\u672C\u751F\u6D3B\u3002"
));

// 二级标题
body.Append(CreateHeading2("\uFF08\u4E00\uFF09\u57FA\u672C\u539F\u5219"));  // （一）基本原则

body.Append(CreateBodyPara(
    "\u575A\u6301\u5E94\u4FDD\u5C3D\u4FDD\u3001\u5E94\u6551\u5C3D\u6551\uFF0C" +
    "\u505A\u5230\u7CBE\u51C6\u8BC6\u522B\u3001\u7CBE\u51C6\u6551\u52A9\u3002" +
    "\u6839\u636E\u300A\u6700\u4F4E\u751F\u6D3B\u4FDD\u969C\u5BA1\u6838\u786E\u8BA4\u529E\u6CD5\u300B" +
    "\uFF08\u6C11\u53D1\u30142021\u301557\u53F7\uFF09\u7B2C\u5341\u4E8C\u6761\u89C4\u5B9A\uFF0C" +
    "\u4F4E\u4FDD\u5BA1\u6838\u786E\u8BA4\u5E94\u5F53\u81EA\u53D7\u7406\u4E4B\u65E5\u8D7730\u4E2A\u5DE5\u4F5C\u65E5\u5185\u5B8C\u6210\u3002"
));

body.Append(CreateHeading2("\uFF08\u4E8C\uFF09\u5DE5\u4F5C\u76EE\u6807"));  // （二）工作目标

body.Append(CreateBodyPara(
    "2025\u5E74\u5E95\u524D\uFF0C\u5B9E\u73B0\u5168\u5E02\u4F4E\u6536\u5165\u4EBA\u53E3" +
    "\u52A8\u6001\u76D1\u6D4B\u5168\u8986\u76D6\uFF0C\u6551\u52A9\u65F6\u6548\u63D0\u534750%\u4EE5\u4E0A\u3002"
));

// 一级标题
body.Append(CreateHeading1("\u4E8C\u3001\u91CD\u70B9\u4EFB\u52A1"));  // 二、重点任务

// 三级标题
body.Append(CreateHeading3("1.\u5B8C\u5584\u4E3B\u52A8\u53D1\u73B0\u673A\u5236"));  // 1.完善主动发现机制

body.Append(CreateBodyPara(
    "\u4F9D\u6258\u201C\u4E00\u7F51\u7EDF\u7BA1\u201D\u5E73\u53F0\uFF0C" +
    "\u5EFA\u7ACB\u591A\u90E8\u95E8\u6570\u636E\u5171\u4EAB\u673A\u5236\uFF0C" +
    "\u5B9E\u73B0\u56F0\u96BE\u7FA4\u4F17\u65E9\u53D1\u73B0\u3001\u65E9\u4ECB\u5165\u3001\u65E9\u6551\u52A9\u3002"
));

body.Append(CreateHeading1("\u4E09\u3001\u4FDD\u969C\u63AA\u65BD"));  // 三、保障措施

body.Append(CreateBodyPara(
    "\u5404\u533A\u6C11\u653F\u5C40\u8981\u9AD8\u5EA6\u91CD\u89C6\uFF0C" +
    "\u52A0\u5F3A\u7EC4\u7EC7\u9886\u5BFC\uFF0C\u786E\u4FDD\u5404\u9879\u4EFB\u52A1\u843D\u5230\u5B9E\u5904\u3002"
));

// ══════════════════════════════════════════════
// 落款
// ══════════════════════════════════════════════
body.Append(new Paragraph(
    new ParagraphProperties(
        new SpacingBetweenLines { Before = "600" }
    )
));

body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Right },
        new SpacingBetweenLines { After = "100", Line = "570", LineRule = LineSpacingRuleValues.Exact }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" }
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
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" }
        ),
        new Text(docDate)
    )
));

// ══════════════════════════════════════════════
// 版记（抄送）
// ══════════════════════════════════════════════
// 上分隔线
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
            new FontSize { Val = "24" },
            new FontSizeComplexScript { Val = "24" }
        ),
        new Text("\u6284\u9001\uFF1A" + ccOrgs + "\u3002")  // 抄送：市财政局、市人社局。
    )
));

// 下分隔线
body.Append(new Paragraph(
    new ParagraphProperties(
        new ParagraphBorders(
            new BottomBorder { Val = BorderValues.Single, Size = 4, Color = GOV_RED, Space = 1 }
        ),
        new SpacingBetweenLines { Before = "0", After = "0" }
    )
));

// ══════════════════════════════════════════════
// 页面设置（SectionProperties 必须是 body 最后一个子元素）
// ══════════════════════════════════════════════

// 页脚（页码）
var footerPart = mainPart.AddNewPart<FooterPart>();
var footerId = mainPart.GetIdOfPart(footerPart);

var footerPara = new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center }
    )
);
// — PAGE —
footerPara.Append(new Run(
    new RunProperties(
        new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
        new FontSize { Val = "24" },
        new FontSizeComplexScript { Val = "24" }
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
        new FontSize { Val = "24" },
        new FontSizeComplexScript { Val = "24" }
    ),
    new Text(" \u2014") { Space = SpaceProcessingModeValues.Preserve }
));
footerPart.Footer = new Footer(footerPara);

body.Append(new SectionProperties(
    new FooterReference { Type = HeaderFooterValues.Default, Id = footerId },
    new PageSize { Width = A4W, Height = A4H },
    new PageMargin {
        Top = MTop, Bottom = MBot, Left = (uint)MLeft, Right = (uint)MRight,
        Header = 720, Footer = 720
    }
));

mainPart.Document.Append(body);
doc.Save();
Console.WriteLine($"\u2705 \u751F\u6210\u5B8C\u6210\uFF1A{outputFile}");

// ══════════════════════════════════════════════
// 辅助方法
// ══════════════════════════════════════════════

/// <summary>创建正文段落（三号仿宋，行距28.5磅，首行缩进2字符）</summary>
static Paragraph CreateBodyPara(string text, bool bold = false, bool indent = true)
{
    var pProps = new ParagraphProperties(
        new Justification { Val = JustificationValues.Both },
        new SpacingBetweenLines { Line = "570", LineRule = LineSpacingRuleValues.Exact, After = "0" }
    );
    if (indent)
        pProps.Append(new Indentation { FirstLine = "640" });  // 2字符 ≈ 640 twips at 三号

    var rProps = new RunProperties(
        new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
        new FontSize { Val = "32" },
        new FontSizeComplexScript { Val = "32" }
    );
    if (bold) rProps.Append(new Bold());

    return new Paragraph(pProps, new Run(rProps, new Text(text)));
}

/// <summary>一级标题（黑体三号，如"一、总体要求"）</summary>
static Paragraph CreateHeading1(string text)
{
    return new Paragraph(
        new ParagraphProperties(
            new ParagraphStyleId { Val = "Heading1" },
            new Justification { Val = JustificationValues.Left },
            new SpacingBetweenLines { Before = "200", After = "100", Line = "570", LineRule = LineSpacingRuleValues.Exact },
            new Indentation { FirstLine = "0" }
        ),
        new Run(
            new RunProperties(
                new RunFonts { Ascii = "SimHei", HighAnsi = "SimHei", EastAsia = "SimHei" },
                new FontSize { Val = "32" },
                new FontSizeComplexScript { Val = "32" },
                new Bold { Val = false }
            ),
            new Text(text)
        )
    );
}

/// <summary>二级标题（楷体三号，如"（一）基本原则"）</summary>
static Paragraph CreateHeading2(string text)
{
    return new Paragraph(
        new ParagraphProperties(
            new ParagraphStyleId { Val = "Heading2" },
            new Justification { Val = JustificationValues.Left },
            new SpacingBetweenLines { Before = "100", After = "50", Line = "570", LineRule = LineSpacingRuleValues.Exact },
            new Indentation { FirstLine = "640" }
        ),
        new Run(
            new RunProperties(
                new RunFonts { Ascii = "KaiTi", HighAnsi = "KaiTi", EastAsia = "KaiTi" },
                new FontSize { Val = "32" },
                new FontSizeComplexScript { Val = "32" }
            ),
            new Text(text)
        )
    );
}

/// <summary>三级标题（仿宋三号加粗，如"1.完善主动发现机制"）</summary>
static Paragraph CreateHeading3(string text)
{
    return new Paragraph(
        new ParagraphProperties(
            new Justification { Val = JustificationValues.Left },
            new SpacingBetweenLines { Before = "100", After = "50", Line = "570", LineRule = LineSpacingRuleValues.Exact },
            new Indentation { FirstLine = "640" }
        ),
        new Run(
            new RunProperties(
                new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
                new FontSize { Val = "32" },
                new FontSizeComplexScript { Val = "32" },
                new Bold()
            ),
            new Text(text)
        )
    );
}

/// <summary>添加样式定义</summary>
static void AddStyles(MainDocumentPart mainPart)
{
    var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
    stylesPart.Styles = new Styles();

    // Normal 样式
    stylesPart.Styles.Append(new Style(
        new StyleName { Val = "Normal" },
        new StyleParagraphProperties(
            new SpacingBetweenLines { Line = "570", LineRule = LineSpacingRuleValues.Exact, After = "0" },
            new Indentation { FirstLine = "640" }
        ),
        new StyleRunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" },
            new Color { Val = BLACK }
        )
    ) { Type = StyleValues.Paragraph, StyleId = "Normal", Default = true });

    // Heading1
    stylesPart.Styles.Append(new Style(
        new StyleName { Val = "heading 1" },
        new BasedOn { Val = "Normal" },
        new StyleParagraphProperties(
            new KeepNext(),
            new KeepLines(),
            new OutlineLevel { Val = 0 },
            new Indentation { FirstLine = "0" }
        ),
        new StyleRunProperties(
            new RunFonts { Ascii = "SimHei", HighAnsi = "SimHei", EastAsia = "SimHei" },
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" }
        )
    ) { Type = StyleValues.Paragraph, StyleId = "Heading1" });

    // Heading2
    stylesPart.Styles.Append(new Style(
        new StyleName { Val = "heading 2" },
        new BasedOn { Val = "Normal" },
        new StyleParagraphProperties(
            new KeepNext(),
            new KeepLines(),
            new OutlineLevel { Val = 1 }
        ),
        new StyleRunProperties(
            new RunFonts { Ascii = "KaiTi", HighAnsi = "KaiTi", EastAsia = "KaiTi" },
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" }
        )
    ) { Type = StyleValues.Paragraph, StyleId = "Heading2" });

    // Heading3
    stylesPart.Styles.Append(new Style(
        new StyleName { Val = "heading 3" },
        new BasedOn { Val = "Normal" },
        new StyleParagraphProperties(
            new KeepNext(),
            new KeepLines(),
            new OutlineLevel { Val = 2 }
        ),
        new StyleRunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new Bold(),
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" }
        )
    ) { Type = StyleValues.Paragraph, StyleId = "Heading3" });
}

/// <summary>创建政策索引表（三线表）</summary>
static Table CreatePolicyIndexTable(MainDocumentPart mainPart, (string docNum, string name, string clause, string url)[] policies)
{
    var table = new Table();

    table.Append(new TableProperties(
        new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
        new TableBorders(
            new TopBorder { Val = BorderValues.Single, Size = 12, Color = BLACK },
            new BottomBorder { Val = BorderValues.Single, Size = 12, Color = BLACK },
            new LeftBorder { Val = BorderValues.Nil },
            new RightBorder { Val = BorderValues.Nil },
            new InsideHorizontalBorder { Val = BorderValues.Nil },
            new InsideVerticalBorder { Val = BorderValues.Nil }
        ),
        new TableCellMarginDefault(
            new TopMargin { Width = "80", Type = TableWidthUnitValues.Dxa },
            new TableCellLeftMargin { Width = 120, Type = TableWidthValues.Dxa },
            new BottomMargin { Width = "80", Type = TableWidthUnitValues.Dxa },
            new TableCellRightMargin { Width = 120, Type = TableWidthValues.Dxa }
        )
    ));

    var widths = new[] { "2000", "2400", "1800", "2800" };
    table.Append(new TableGrid(
        new GridColumn { Width = widths[0] },
        new GridColumn { Width = widths[1] },
        new GridColumn { Width = widths[2] },
        new GridColumn { Width = widths[3] }
    ));

    // 表头
    var headerRow = new TableRow(new TableRowProperties(new TableHeader()));
    string[] headers = { "\u6587\u53F7", "\u653F\u7B56\u540D\u79F0", "\u5F15\u7528\u6761\u6B3E", "\u539F\u6587\u94FE\u63A5" };
    for (int i = 0; i < headers.Length; i++)
    {
        var cellProps = new TableCellProperties(
            new TableCellWidth { Width = widths[i], Type = TableWidthUnitValues.Dxa },
            new TableCellBorders(
                new BottomBorder { Val = BorderValues.Single, Size = 6, Color = BLACK }
            )
        );
        headerRow.Append(new TableCell(cellProps,
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Center },
                    new SpacingBetweenLines { Before = "0", After = "0", Line = "400", LineRule = LineSpacingRuleValues.Exact },
                    new Indentation { FirstLine = "0" }
                ),
                new Run(
                    new RunProperties(
                        new RunFonts { Ascii = "SimHei", HighAnsi = "SimHei", EastAsia = "SimHei" },
                        new FontSize { Val = "24" },
                        new FontSizeComplexScript { Val = "24" },
                        new Bold()
                    ),
                    new Text(headers[i])
                )
            )
        ));
    }
    table.Append(headerRow);

    // 数据行
    foreach (var p in policies)
    {
        var row = new TableRow();
        string[] cells = { p.docNum, p.name, p.clause, "" };
        for (int i = 0; i < cells.Length; i++)
        {
            var cellProps = new TableCellProperties(
                new TableCellWidth { Width = widths[i], Type = TableWidthUnitValues.Dxa }
            );

            Paragraph cellPara;
            if (i == 3 && !string.IsNullOrEmpty(p.url))
            {
                // 超链接
                var relId = mainPart.AddHyperlinkRelationship(new Uri(p.url), true).Id;
                cellPara = new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { Before = "0", After = "0", Line = "400", LineRule = LineSpacingRuleValues.Exact },
                        new Indentation { FirstLine = "0" }
                    ),
                    new Hyperlink(new Run(
                        new RunProperties(
                            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
                            new FontSize { Val = "21" },
                            new FontSizeComplexScript { Val = "21" },
                            new Color { Val = "0563C1" },
                            new Underline { Val = UnderlineValues.Single }
                        ),
                        new Text("\u94FE\u63A5")  // 链接
                    )) { Id = relId }
                );
            }
            else
            {
                cellPara = new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { Before = "0", After = "0", Line = "400", LineRule = LineSpacingRuleValues.Exact },
                        new Indentation { FirstLine = "0" }
                    ),
                    new Run(
                        new RunProperties(
                            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
                            new FontSize { Val = "21" },
                            new FontSizeComplexScript { Val = "21" }
                        ),
                        new Text(cells[i])
                    )
                );
            }
            row.Append(new TableCell(cellProps, cellPara));
        }
        table.Append(row);
    }

    return table;
}
