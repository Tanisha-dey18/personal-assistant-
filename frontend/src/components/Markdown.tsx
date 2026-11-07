import { Check, Copy } from "lucide-react";
import { memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function CodeBlock({ children, className }: { children?: React.ReactNode; className?: string }) {
  const [copied, setCopied] = useState(false);
  const lang = /language-(\w+)/.exec(className || "")?.[1];
  const text = String(children ?? "").replace(/\n$/, "");
  return (
    <div className="group relative">
      <div className="absolute right-2 top-2 flex items-center gap-2 opacity-0 transition group-hover:opacity-100">
        {lang && <span className="text-[10px] uppercase tracking-wider text-slate-500">{lang}</span>}
        <button className="rounded-md bg-white/10 p-1 text-slate-300 hover:bg-white/20" aria-label="Copy code"
          onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>
      <pre><code>{text}</code></pre>
    </div>
  );
}

function Markdown({ text, streaming }: { text: string; streaming?: boolean }) {
  return (
    <div className={"prose-astra" + (streaming ? " [&>*:last-child]:cursor-blink" : "")}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: (p) => <a {...p} target="_blank" rel="noreferrer noopener" />,
          pre: ({ children }) => <>{children}</>,
          code: ({ className, children, ...rest }) => {
            const isBlock = /language-/.test(className || "") || String(children).includes("\n");
            return isBlock ? <CodeBlock className={className}>{children}</CodeBlock> : <code className={className} {...rest}>{children}</code>;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

export default memo(Markdown);
