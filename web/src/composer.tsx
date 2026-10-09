import { useState } from "react";

/** A piece of a unit's diff chosen as context for the next turn. */
export interface Attachment {
  file: string;
  lines: [number, number];
  hunk: string;
  text: string;
  /** The lines are changes no commit holds yet. */
  uncommitted?: boolean;
}

export interface Turn {
  prompt: string;
  attachments: Attachment[];
}

interface ComposerProps {
  /** Why the composer cannot take input; absent when it can. */
  disabledReason?: string;
  attachments: Attachment[];
  onSend: (turn: Turn) => void;
}

/** The chat box of the agent tab: the attachments as removable chips, and a prompt. */
export function Composer({ disabledReason, attachments, onSend }: ComposerProps) {
  const [removed, setRemoved] = useState<Attachment[]>([]);
  const [prompt, setPrompt] = useState("");
  const kept = attachments.filter((a) => !removed.includes(a));
  const disabled = disabledReason !== undefined;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSend({ prompt, attachments: kept });
        setPrompt("");
      }}
    >
      {disabled && <p>{disabledReason}</p>}
      <ul>
        {kept.map((a) => (
          <li key={`${a.file}:${a.lines[0]}-${a.lines[1]}`}>
            {a.file}:{a.lines[0]}-{a.lines[1]}
            <button
              type="button"
              aria-label={`Remove ${a.file}`}
              onClick={() => setRemoved([...removed, a])}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <textarea
        value={prompt}
        disabled={disabled}
        aria-label="Message"
        onChange={(event) => setPrompt(event.target.value)}
      />
      <button type="submit" disabled={disabled}>
        Send
      </button>
    </form>
  );
}
