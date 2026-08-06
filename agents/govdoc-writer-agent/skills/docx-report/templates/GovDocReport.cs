// GovDocReport.cs — 内部报告模板（只读参考，不要直接修改）
// 适用于：救助方案、审计报告、评估报告等内部文档
// 特点：封面 + 目录占位 + 正文（含表格）+ 政策索引表
// 与红头文件的区别：无版头红线，有封面页，表格更多
//
// 用法：agent 在 cwd 下创建 Program.cs，参考本文件编写，然后执行构建

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

string outputFile = args.Length > 0 ? args[0] : "report.docx";

// ── 报告元数据（按需修改） ──
string reportTitle = "\u4E0A\u6D77\u5E02\u6C11\u653F\u5C40\u7CBE\u51C6\u6551\u52A9\u65B9\u6848";  // 上海市民政局精准救助方案
string reportSubtitle = "\u7F16\u53F7\uFF1APLN-2025-0001";  // 编号：PLN-2025-0001
string reportOrg = "\u4E0A\u6D77\u5E02\u6C11\u653F\u5C40";  // 上海市民政局
string reportDate = "2025\u5E742\u670812\u65E5";              // 2025年2月12日
string confidential = "\u5185\u90E8\u8D44\u6599";             // 内部资料

// ── 常量 ──
const string BLACK = "000000";
const string GRAY = "666666";
const string ACCENT = "1F4E79";
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
// 封面页
// ══════════════════════════════════════════════

// 密级标识（右上角）
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Right },
        new SpacingBetweenLines { Before = "200", After = "0" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "24" },
            new FontSizeComplexScript { Val = "24" },
            new Color { Val = "CC0000" }
        ),
        new Text(confidential)
    )
));

// 空行留白
for (int i = 0; i < 6; i++)
    body.Append(new Paragraph(new ParagraphProperties(
        new SpacingBetweenLines { Before = "0", After = "0", Line = "400", LineRule = LineSpacingRuleValues.Exact }
    )));

// 报告标题
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { Before = "0", After = "200" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "SimHei", HighAnsi = "SimHei", EastAsia = "SimHei" },
            new FontSize { Val = "52" },
            new FontSizeComplexScript { Val = "52" },
            new Color { Val = ACCENT }
        ),
        new Text(reportTitle)
    )
));

// 副标题（编号）
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { Before = "100", After = "600" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" },
            new Color { Val = GRAY }
        ),
        new Text(reportSubtitle)
    )
));

// 空行
for (int i = 0; i < 4; i++)
    body.Append(new Paragraph(new ParagraphProperties(
        new SpacingBetweenLines { Before = "0", After = "0", Line = "400", LineRule = LineSpacingRuleValues.Exact }
    )));

// 编制单位 + 日期
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { After = "100" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" }
        ),
        new Text(reportOrg)
    )
));

body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { After = "0" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" }
        ),
        new Text(reportDate)
    )
));

// ── 封面分页 ──
body.Append(new Paragraph(
    new ParagraphProperties(new SectionProperties(
        new PageSize { Width = A4W, Height = A4H },
        new PageMargin { Top = MTop, Bottom = MBot, Left = (uint)MLeft, Right = (uint)MRight, Header = 720, Footer = 720 }
    ))
));

// ══════════════════════════════════════════════
// 目录占位页（Word 打开后按 F9 更新）
// ══════════════════════════════════════════════
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { Before = "400", After = "400" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "SimHei", HighAnsi = "SimHei", EastAsia = "SimHei" },
            new FontSize { Val = "36" },
            new FontSizeComplexScript { Val = "36" }
        ),
        new Text("\u76EE  \u5F55")  // 目  录
    )
));

// TOC 域代码
body.Append(new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" TOC \\o \"1-3\" \\h \\z \\u ")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("\uFF08\u6253\u5F00\u6587\u6863\u540E\u6309 F9 \u66F4\u65B0\u76EE\u5F55\uFF09")),  // （打开文档后按 F9 更新目录）
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
));

// 目录分页
body.Append(new Paragraph(
    new ParagraphProperties(new SectionProperties(
        new PageSize { Width = A4W, Height = A4H },
        new PageMargin { Top = MTop, Bottom = MBot, Left = (uint)MLeft, Right = (uint)MRight, Header = 720, Footer = 720 }
    ))
));

// ══════════════════════════════════════════════
// 正文
// ══════════════════════════════════════════════

// 一级标题
body.Append(CreateHeading1("\u4E00\u3001\u57FA\u672C\u60C5\u51B5"));  // 一、基本情况

body.Append(CreateBodyPara(
    "\u672C\u62A5\u544A\u6839\u636E\u6570\u636E\u6D77\u76D1\u6D4B\u9884\u8B66\u4FE1\u606F\uFF0C" +
    "\u5BF9\u6D89\u4E8B\u5BB6\u5EAD\u8FDB\u884C\u5168\u9762\u8BC4\u4F30\u3002"
));

// 示例表格（家庭信息）
body.Append(CreateHeading2("\uFF08\u4E00\uFF09\u5BB6\u5EAD\u57FA\u672C\u4FE1\u606F"));  // （一）家庭基本信息

body.Append(CreateInfoTable(mainPart, new[] {
    ("\u6237\u4E3B", "\u738B\u67D0"),                    // 户主, 王某
    ("\u5BB6\u5EAD\u4EBA\u53E3", "3\u4EBA"),             // 家庭人口, 3人
    ("\u5BB6\u5EAD\u5730\u5740", "\u4E0A\u6D77\u5E02\u9759\u5B89\u533A\u67D0\u8DEF\u67D0\u53F7"),  // 家庭地址
    ("\u6551\u52A9\u7C7B\u522B", "\u4F4E\u4FDD"),        // 救助类别, 低保
    ("\u6708\u6551\u52A9\u6807\u51C6", "1,510 \u5143/\u4EBA")  // 月救助标准
}));

body.Append(CreateHeading1("\u4E8C\u3001\u98CE\u9669\u8BC4\u4F30"));  // 二、风险评估

body.Append(CreateBodyPara(
    "\u7ECF\u591A\u7EF4\u6570\u636E\u4EA4\u53C9\u6BD4\u5BF9\uFF0C" +
    "\u8BE5\u5BB6\u5EAD\u5B58\u5728\u4EE5\u4E0B\u98CE\u9669\u56E0\u7D20\uFF1A"
));

body.Append(CreateHeading1("\u4E09\u3001\u653F\u7B56\u5339\u914D"));  // 三、政策匹配

body.Append(CreateBodyPara(
    "\u6839\u636E\u300A\u4E0A\u6D77\u5E02\u793E\u4F1A\u6551\u52A9\u6761\u4F8B\u300B" +
    "\uFF08\u5E02\u4EBA\u5927\u5E38\u59D4\u4F1A\u516C\u544A\u7B2C8\u53F7\uFF09\u7B2C\u5341\u4E8C\u6761\uFF0C" +
    "\u8BE5\u5BB6\u5EAD\u7B26\u5408\u4EE5\u4E0B\u6551\u52A9\u653F\u7B56\uFF1A"
));

body.Append(CreateHeading1("\u56DB\u3001\u6551\u52A9\u65B9\u6848"));  // 四、救助方案

body.Append(CreateBodyPara(
    "\u7EFC\u5408\u4EE5\u4E0A\u8BC4\u4F30\uFF0C\u5236\u5B9A\u5982\u4E0B\u4E00\u6237\u4E00\u7B56\u6551\u52A9\u65B9\u6848\uFF1A"
));

// ══════════════════════════════════════════════
// 政策依据索引表
// ══════════════════════════════════════════════
body.Append(CreateHeading1("\u4E94\u3001\u653F\u7B56\u4F9D\u636E\u7D22\u5F15"));  // 五、政策依据索引

body.Append(CreatePolicyIndexTable(mainPart, new[] {
    ("\u5E02\u4EBA\u5927\u5E38\u59D4\u4F1A\u516C\u544A\u7B2C8\u53F7",
     "\u4E0A\u6D77\u5E02\u793E\u4F1A\u6551\u52A9\u6761\u4F8B",
     "\u7B2C\u5341\u4E8C\u6761",
     "https://www.shanghai.gov.cn/nw12344/20200814/0001-12344_63423.html"),
    ("\u6CAA\u6C11\u89C4\u30142019\u30157\u53F7",
     "\u4E0A\u6D77\u5E02\u6700\u4F4E\u751F\u6D3B\u4FDD\u969C\u5BA1\u6838\u786E\u8BA4\u529E\u6CD5",
     "\u7B2C\u516D\u6761",
     "https://mzj.sh.gov.cn/MZ_zhengce_gfxwj-shehui/20220301/a7b8c9d0e1f2.html")
}));

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
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" }
        ),
        new Text(reportOrg)
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
        new Text(reportDate)
    )
));

// ══════════════════════════════════════════════
// 页脚（页码）+ 页面设置
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
Console.WriteLine($"\u2705 \u62A5\u544A\u751F\u6210\u5B8C\u6210\uFF1A{outputFile}");

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
                new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" },
                new Bold { Val = false }
            ),
            new Text(text)
        )
    );
}

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
                new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
            ),
            new Text(text)
        )
    );
}

/// <summary>创建键值对信息表（两列表格）</summary>
static Table CreateInfoTable(MainDocumentPart mainPart, (string key, string value)[] items)
{
    var table = new Table();
    table.Append(new TableProperties(
        new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
        new TableBorders(
            new TopBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
            new BottomBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
            new LeftBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
            new RightBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
            new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4, Color = "CCCCCC" },
            new InsideVerticalBorder { Val = BorderValues.Single, Size = 4, Color = "CCCCCC" }
        )
    ));
    table.Append(new TableGrid(new GridColumn { Width = "3000" }, new GridColumn { Width = "6000" }));

    foreach (var (key, value) in items)
    {
        var row = new TableRow();
        // Key cell (gray background)
        row.Append(new TableCell(
            new TableCellProperties(
                new TableCellWidth { Width = "3000", Type = TableWidthUnitValues.Dxa },
                new Shading { Val = ShadingPatternValues.Clear, Fill = "F2F2F2" }
            ),
            new Paragraph(
                new ParagraphProperties(
                    new SpacingBetweenLines { Before = "40", After = "40", Line = "400", LineRule = LineSpacingRuleValues.Exact },
                    new Indentation { FirstLine = "0" }
                ),
                new Run(
                    new RunProperties(
                        new RunFonts { Ascii = "SimHei", HighAnsi = "SimHei", EastAsia = "SimHei" },
                        new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }
                    ),
                    new Text(key)
                )
            )
        ));
        // Value cell
        row.Append(new TableCell(
            new TableCellProperties(new TableCellWidth { Width = "6000", Type = TableWidthUnitValues.Dxa }),
            new Paragraph(
                new ParagraphProperties(
                    new SpacingBetweenLines { Before = "40", After = "40", Line = "400", LineRule = LineSpacingRuleValues.Exact },
                    new Indentation { FirstLine = "0" }
                ),
                new Run(
                    new RunProperties(
                        new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
                        new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }
                    ),
                    new Text(value)
                )
            )
        ));
        table.Append(row);
    }
    return table;
}

/// <summary>创建政策索引表（三线表）</summary>
static Table CreatePolicyIndexTable(MainDocumentPart mainPart, (string docNum, string name, string clause, string url)[] policies)
{
    var table = new Table();
    table.Append(new TableProperties(
        new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
        new TableBorders(
            new TopBorder { Val = BorderValues.Single, Size = 12, Color = "000000" },
            new BottomBorder { Val = BorderValues.Single, Size = 12, Color = "000000" },
            new LeftBorder { Val = BorderValues.Nil },
            new RightBorder { Val = BorderValues.Nil },
            new InsideHorizontalBorder { Val = BorderValues.Nil },
            new InsideVerticalBorder { Val = BorderValues.Nil }
        )
    ));
    var widths = new[] { "2000", "2400", "1800", "2800" };
    table.Append(new TableGrid(
        new GridColumn { Width = widths[0] }, new GridColumn { Width = widths[1] },
        new GridColumn { Width = widths[2] }, new GridColumn { Width = widths[3] }
    ));

    // 表头
    var headerRow = new TableRow(new TableRowProperties(new TableHeader()));
    string[] headers = { "\u6587\u53F7", "\u653F\u7B56\u540D\u79F0", "\u5F15\u7528\u6761\u6B3E", "\u539F\u6587\u94FE\u63A5" };
    for (int i = 0; i < headers.Length; i++)
    {
        headerRow.Append(new TableCell(
            new TableCellProperties(
                new TableCellWidth { Width = widths[i], Type = TableWidthUnitValues.Dxa },
                new TableCellBorders(new BottomBorder { Val = BorderValues.Single, Size = 6, Color = "000000" })
            ),
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Center },
                    new SpacingBetweenLines { Before = "0", After = "0", Line = "400", LineRule = LineSpacingRuleValues.Exact },
                    new Indentation { FirstLine = "0" }
                ),
                new Run(
                    new RunProperties(
                        new RunFonts { Ascii = "SimHei", HighAnsi = "SimHei", EastAsia = "SimHei" },
                        new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }, new Bold()
                    ),
                    new Text(headers[i])
                )
            )
        ));
    }
    table.Append(headerRow);

    foreach (var p in policies)
    {
        var row = new TableRow();
        string[] cells = { p.docNum, p.name, p.clause, "" };
        for (int i = 0; i < cells.Length; i++)
        {
            Paragraph cellPara;
            if (i == 3 && !string.IsNullOrEmpty(p.url))
            {
                var relId = mainPart.AddHyperlinkRelationship(new Uri(p.url), true).Id;
                cellPara = new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { Before = "0", After = "0", Line = "400", LineRule = LineSpacingRuleValues.Exact },
                        new Indentation { FirstLine = "0" }
                    ),
                    new Hyperlink(new Run(
                        new RunProperties(
                            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
                            new FontSize { Val = "21" }, new FontSizeComplexScript { Val = "21" },
                            new Color { Val = "0563C1" }, new Underline { Val = UnderlineValues.Single }
                        ),
                        new Text("\u94FE\u63A5")
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
                            new FontSize { Val = "21" }, new FontSizeComplexScript { Val = "21" }
                        ),
                        new Text(cells[i])
                    )
                );
            }
            row.Append(new TableCell(
                new TableCellProperties(new TableCellWidth { Width = widths[i], Type = TableWidthUnitValues.Dxa }),
                cellPara
            ));
        }
        table.Append(row);
    }
    return table;
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

    stylesPart.Styles.Append(new Style(
        new StyleName { Val = "heading 1" },
        new BasedOn { Val = "Normal" },
        new StyleParagraphProperties(new KeepNext(), new KeepLines(), new OutlineLevel { Val = 0 }, new Indentation { FirstLine = "0" }),
        new StyleRunProperties(
            new RunFonts { Ascii = "SimHei", HighAnsi = "SimHei", EastAsia = "SimHei" },
            new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
        )
    ) { Type = StyleValues.Paragraph, StyleId = "Heading1" });

    stylesPart.Styles.Append(new Style(
        new StyleName { Val = "heading 2" },
        new BasedOn { Val = "Normal" },
        new StyleParagraphProperties(new KeepNext(), new KeepLines(), new OutlineLevel { Val = 1 }),
        new StyleRunProperties(
            new RunFonts { Ascii = "KaiTi", HighAnsi = "KaiTi", EastAsia = "KaiTi" },
            new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
        )
    ) { Type = StyleValues.Paragraph, StyleId = "Heading2" });

    stylesPart.Styles.Append(new Style(
        new StyleName { Val = "heading 3" },
        new BasedOn { Val = "Normal" },
        new StyleParagraphProperties(new KeepNext(), new KeepLines(), new OutlineLevel { Val = 2 }),
        new StyleRunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new Bold(), new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
        )
    ) { Type = StyleValues.Paragraph, StyleId = "Heading3" });
}
