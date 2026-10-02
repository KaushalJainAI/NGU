import React from "react";

/**
 * Minimal, XSS-safe Markdown renderer for assistant chat replies.
 *
 * Supports the small subset the assistant is instructed to emit: **bold**,
 * *italic* / _italic_, bullet lists (-, *, •), numbered lists, and
 * paragraphs / line breaks. Everything is rendered as React elements (no
 * dangerouslySetInnerHTML, no raw HTML), so untrusted model output can never
 * inject markup.
 */

const renderInline = (text: string, keyPrefix: string): React.ReactNode[] => {
  const nodes: React.ReactNode[] = [];
  // Split while keeping the **bold** / *italic* / _italic_ delimiters.
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*\n]+\*|_[^_\n]+_)/g);
  parts.forEach((part, i) => {
    if (!part) return;
    if (/^\*\*[^*]+\*\*$/.test(part)) {
      nodes.push(<strong key={`${keyPrefix}-b-${i}`}>{part.slice(2, -2)}</strong>);
    } else if (/^\*[^*]+\*$/.test(part) || /^_[^_]+_$/.test(part)) {
      nodes.push(<em key={`${keyPrefix}-i-${i}`}>{part.slice(1, -1)}</em>);
    } else {
      nodes.push(<React.Fragment key={`${keyPrefix}-t-${i}`}>{part}</React.Fragment>);
    }
  });
  return nodes;
};

const ChatMarkdown: React.FC<{ text: string }> = ({ text }) => {
  const lines = (text || "").replace(/\r\n/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let listItems: string[] = [];
  let listOrdered = false;
  let listOpen = false;
  let para: string[] = [];

  const flushPara = (key: string) => {
    if (para.length) {
      blocks.push(
        <p key={key} className="leading-relaxed">
          {renderInline(para.join(" "), key)}
        </p>
      );
      para = [];
    }
  };
  const flushList = (key: string) => {
    if (listOpen) {
      const items = listItems.map((it, i) => (
        <li key={`${key}-li-${i}`}>{renderInline(it, `${key}-li-${i}`)}</li>
      ));
      blocks.push(
        listOrdered ? (
          <ol key={key} className="list-decimal pl-5 space-y-0.5">
            {items}
          </ol>
        ) : (
          <ul key={key} className="list-disc pl-5 space-y-0.5">
            {items}
          </ul>
        )
      );
      listItems = [];
      listOpen = false;
    }
  };

  lines.forEach((raw, idx) => {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet) {
      flushPara(`p-${idx}`);
      if (listOpen && listOrdered) flushList(`l-${idx}`);
      listOrdered = false;
      listOpen = true;
      listItems.push(bullet[1]);
    } else if (ordered) {
      flushPara(`p-${idx}`);
      if (listOpen && !listOrdered) flushList(`l-${idx}`);
      listOrdered = true;
      listOpen = true;
      listItems.push(ordered[1]);
    } else if (line.trim() === "") {
      flushPara(`p-${idx}`);
      flushList(`l-${idx}`);
    } else {
      flushList(`l-${idx}`);
      para.push(line.trim());
    }
  });
  flushPara("p-end");
  flushList("l-end");

  return <div className="space-y-2">{blocks}</div>;
};

export default ChatMarkdown;
