import ReactMarkdown from "react-markdown";

export function Markdown({ text }: { text: string }) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        skipHtml
        disallowedElements={["img"]}
        urlTransform={(url) => /^https?:\/\//i.test(url) && URL.canParse(url) ? url : ""}
        components={{
          a: ({ children, href }) => href
            ? <a href={href} referrerPolicy="no-referrer">{children}</a>
            : <>{children}</>,
        }}
      >{text}</ReactMarkdown>
    </div>
  );
}
