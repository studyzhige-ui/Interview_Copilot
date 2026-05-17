import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * Lightweight markdown renderer for chat bubbles + report bodies.
 *
 * We deliberately scope styling to a single wrapper so chat-bubble defaults
 * (rounded corners, padding) still apply, and override the list / heading /
 * code defaults that react-markdown ships with via tailwind class names.
 *
 * No `rehype-raw` / no `dangerouslySetInnerHTML` — assistant content is
 * treated as plain markdown text only.
 */
export function MarkdownBody({ source }: { source: string }) {
  return (
    <div className="md-body break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p:  ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="list-disc pl-5 mb-2 last:mb-0 space-y-0.5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 last:mb-0 space-y-0.5">{children}</ol>,
          li: ({ children }) => <li className="leading-[1.65]">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          em:     ({ children }) => <em className="italic">{children}</em>,
          h1: ({ children }) => <h3 className="text-[15px] font-semibold mb-1.5 mt-2 first:mt-0">{children}</h3>,
          h2: ({ children }) => <h4 className="text-[14px] font-semibold mb-1.5 mt-2 first:mt-0">{children}</h4>,
          h3: ({ children }) => <h5 className="text-[14px] font-semibold mb-1 mt-1.5 first:mt-0">{children}</h5>,
          h4: ({ children }) => <h6 className="text-[13px] font-semibold mb-1 mt-1.5 first:mt-0">{children}</h6>,
          code: ({ children, className }) => {
            const isBlock = (className ?? '').startsWith('language-');
            if (isBlock) {
              return (
                <pre className="bg-stone-50 border border-stone-200 rounded-md p-2.5 text-[12px] overflow-x-auto my-2 font-mono leading-[1.55]">
                  <code>{children}</code>
                </pre>
              );
            }
            return (
              <code className="bg-stone-200/60 px-1 py-px rounded text-[12.5px] font-mono">
                {children}
              </code>
            );
          },
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-stone-300 pl-3 italic text-stone-600 my-1.5">
              {children}
            </blockquote>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-primary-600 underline underline-offset-2 hover:text-primary-700"
            >
              {children}
            </a>
          ),
          hr: () => <hr className="my-2 border-stone-200" />,
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
