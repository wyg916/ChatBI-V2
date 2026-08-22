import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';


export function sanitizeMarkdownUrl(value: string): string {
  const url = value.trim();
  if (/^https?:\/\//i.test(url) || /^mailto:/i.test(url)) return url;
  if (url.startsWith('/api/v1/') && !url.includes('\\') && !url.includes('..')) return url;
  if (url.startsWith('#') && !/[\s"'<>]/.test(url)) return url;
  return '';
}


export function AnswerMarkdown({ markdown, className }: { markdown: string; className?: string }) {
  return (
    <div className={className ?? 'answer-markdown'} data-testid="answer-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        skipHtml
        urlTransform={sanitizeMarkdownUrl}
        components={{
          a: ({ href, children, ...props }) => {
            const safeHref = sanitizeMarkdownUrl(href ?? '');
            if (!safeHref) return <span>{children}</span>;
            const external = /^https?:\/\//i.test(safeHref);
            return <a {...props} href={safeHref} target={external ? '_blank' : undefined} rel={external ? 'noopener noreferrer' : undefined}>{children}</a>;
          },
          img: ({ alt }) => <span className="answer-markdown-image-placeholder">{alt ? `[图片：${alt}]` : '[图片]'}</span>,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}


export default AnswerMarkdown;
