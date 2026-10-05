// build_report_docx.js -- renders a parsed report structure (see
// report_to_docx.py's parse_markdown_report()) into a styled .docx via
// docx-js. Invoked as: node build_report_docx.js <content.json> <output.docx>

const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  Header, Footer, PageNumber, PageBreak, convertInchesToTwip, ImageRun,
} = require("docx");

const [, , contentPath, outputPath] = process.argv;
const data = JSON.parse(fs.readFileSync(contentPath, "utf-8"));
const { title, subtitle_note, disclaimer_runs, blocks, theme, event_name, image_base_dir } = data;

// Minimal PNG dimension reader (avoids adding an npm dependency just for
// this): a PNG's IHDR chunk always starts at byte 16, width/height are the
// next two big-endian uint32s. Every PNG this suite's own matplotlib
// pipeline produces (savefig(..., dpi=...)) is a standard, uncompressed-
// header PNG, so this is safe for this suite's own generated images --
// not a general-purpose PNG parser.
function pngDimensions(buffer) {
  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
  };
}

const FONT = "Calibri";
const PAGE_WIDTH_DXA = 12240;   // US Letter width, per skill guidance
const PAGE_HEIGHT_DXA = 15840;
const MARGIN = convertInchesToTwip(0.9);
const CONTENT_WIDTH_DXA = PAGE_WIDTH_DXA - 2 * MARGIN;

function runs(inlineRuns, opts = {}) {
  return inlineRuns.map(r => new TextRun({
    text: r.text, bold: r.bold || opts.bold, italics: opts.italics,
    color: opts.color, size: opts.size, font: FONT,
  }));
}

// ---------------------------------------------------------------- title page
const titlePageChildren = [
  new Paragraph({ spacing: { before: 2200 }, children: [] }),
  new Paragraph({
    border: { bottom: { color: theme.accent, space: 8, style: BorderStyle.SINGLE, size: 24 } },
    spacing: { after: 300 },
    children: [new TextRun({ text: " ", size: 2 })],
  }),
  new Paragraph({
    alignment: AlignmentType.LEFT,
    spacing: { after: 120 },
    children: [new TextRun({
      text: theme.badge, bold: true, color: theme.badge_text, font: FONT, size: 20,
      shading: { type: ShadingType.CLEAR, fill: theme.accent },
    })],
  }),
  new Paragraph({
    spacing: { before: 200, after: 100 },
    children: [new TextRun({ text: title, bold: true, size: 56, font: FONT, color: "1A1A1A" })],
  }),
];
if (subtitle_note) {
  titlePageChildren.push(new Paragraph({
    spacing: { after: 600 },
    children: [new TextRun({ text: subtitle_note, italics: true, size: 22, font: FONT, color: "555555" })],
  }));
}
if (disclaimer_runs && disclaimer_runs.length) {
  titlePageChildren.push(new Paragraph({
    spacing: { before: 400 },
    shading: { type: ShadingType.CLEAR, fill: theme.accent_light },
    border: { left: { color: theme.accent, space: 8, style: BorderStyle.SINGLE, size: 18 } },
    indent: { left: 200 },
    children: runs(disclaimer_runs, { size: 20, color: "1A1A1A" }),
  }));
}
titlePageChildren.push(new Paragraph({ children: [new PageBreak()] }));

// -------------------------------------------------------------- body blocks
function tableFromBlock(block) {
  const nCols = block.header.length;
  const colWidth = Math.floor(CONTENT_WIDTH_DXA / nCols);
  const colWidths = Array(nCols).fill(colWidth);

  function cell(inlineRuns, isHeader) {
    return new TableCell({
      width: { size: colWidth, type: WidthType.DXA },
      shading: isHeader
        ? { type: ShadingType.CLEAR, fill: theme.accent }
        : { type: ShadingType.CLEAR, fill: "FFFFFF" },
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      children: [new Paragraph({
        children: runs(inlineRuns, isHeader
          ? { bold: true, color: "FFFFFF", size: 19 }
          : { size: 19 }),
      })],
    });
  }

  const headerRow = new TableRow({
    tableHeader: true,
    cantSplit: true,
    children: block.header.map(h => cell(h, true)),
  });
  const bodyRows = block.rows.map((row, i) => new TableRow({
    cantSplit: true,
    children: row.map(c => cell(c, false)),
  }));

  return new Table({
    columnWidths: colWidths,
    width: { size: CONTENT_WIDTH_DXA, type: WidthType.DXA },
    rows: [headerRow, ...bodyRows],
  });
}

const bodyChildren = [];
for (const block of blocks) {
  if (block.type === "heading") {
    const isL2 = block.level === 2;
    bodyChildren.push(new Paragraph({
      heading: isL2 ? HeadingLevel.HEADING_1 : HeadingLevel.HEADING_2,
      spacing: { before: isL2 ? 420 : 280, after: 160 },
      border: isL2 ? { bottom: { color: theme.accent, space: 4, style: BorderStyle.SINGLE, size: 8 } } : undefined,
      children: [new TextRun({
        text: block.runs.map(r => r.text).join(""),
        bold: true, font: FONT, color: isL2 ? theme.accent : "1A1A1A",
        size: isL2 ? 30 : 24,
      })],
    }));
  } else if (block.type === "paragraph") {
    bodyChildren.push(new Paragraph({
      spacing: { after: 200 },
      children: runs(block.runs, { size: 21 }),
    }));
  } else if (block.type === "bullets") {
    for (const item of block.items) {
      bodyChildren.push(new Paragraph({
        bullet: { level: 0 },
        spacing: { after: 90 },
        children: runs(item, { size: 21 }),
      }));
    }
  } else if (block.type === "table") {
    bodyChildren.push(tableFromBlock(block));
    bodyChildren.push(new Paragraph({ spacing: { after: 240 }, children: [] }));
  } else if (block.type === "caption") {
    bodyChildren.push(new Paragraph({
      spacing: { before: 100, after: 240 },
      children: runs(block.runs, { italics: true, size: 18, color: "666666" }),
    }));
  } else if (block.type === "image") {
    const imgPath = path.join(image_base_dir, block.path);
    if (fs.existsSync(imgPath)) {
      const buffer = fs.readFileSync(imgPath);
      const { width, height } = pngDimensions(buffer);
      // DPI-independent by design: display at the full content width (like
      // the tables above) and derive height from the image's own aspect
      // ratio, rather than assuming a fixed DPI to convert pixel count to a
      // physical size (matplotlib's own dpi= setting varies by generator).
      const displayWidth = CONTENT_WIDTH_DXA;
      const displayHeight = Math.round(displayWidth * (height / width));
      bodyChildren.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 120, after: 60 },
        children: [new ImageRun({
          type: "png",
          data: buffer,
          transformation: {
            width: Math.round(displayWidth / 15),   // DXA -> pixels @ 96 DPI (docx-js expects px)
            height: Math.round(displayHeight / 15),
          },
        })],
      }));
    } else {
      bodyChildren.push(new Paragraph({
        spacing: { after: 120 },
        children: [new TextRun({
          text: `[afbeelding niet gevonden: ${block.path}]`,
          italics: true, color: "AA0000", font: FONT, size: 18,
        })],
      }));
    }
  }
}

// -------------------------------------------------------------------- doc
const doc = new Document({
  sections: [{
    properties: {
      page: {
        size: { width: PAGE_WIDTH_DXA, height: PAGE_HEIGHT_DXA },
        margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { bottom: { color: theme.accent, space: 4, style: BorderStyle.SINGLE, size: 4 } },
          children: [new TextRun({ text: event_name, size: 16, color: "888888", font: FONT })],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: theme.badge + " \u2014 ", size: 16, color: "999999", font: FONT }),
            new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "999999", font: FONT }),
          ],
        })],
      }),
    },
    children: [...titlePageChildren, ...bodyChildren],
  }],
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(outputPath, buffer);
  console.log("written:", outputPath);
});
