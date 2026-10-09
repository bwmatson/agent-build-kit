// The composer of the agent tab: attachments as removable chips, a prompt, and the reason
// it cannot take input while a step runs.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Composer } from "./composer";
import type { Attachment } from "./composer";

const MARKER: Attachment = {
  file: "src/app/marker.py",
  lines: [3, 5],
  hunk: "@@ -3,3 +3,3 @@\n-MARKER = None\n+MARKER = 'added'",
  text: "MARKER = 'added'",
};
const OTHER: Attachment = {
  file: "src/app/other.py",
  lines: [10, 12],
  hunk: "@@ -10,3 +10,3 @@\n-OTHER = 1\n+OTHER = 2",
  text: "OTHER = 2",
};

describe("the composer", () => {
  it("shows one chip for each attachment, naming its file and lines", () => {
    render(<Composer attachments={[MARKER, OTHER]} onSend={vi.fn()} />);

    const chips = screen.getAllByRole("listitem");
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveTextContent("src/app/marker.py");
    expect(chips[0]).toHaveTextContent(/3\D+5/);
    expect(chips[1]).toHaveTextContent("src/app/other.py");
  });

  it("sends the prompt with every attachment still on a chip", async () => {
    const onSend = vi.fn();
    render(<Composer attachments={[MARKER, OTHER]} onSend={onSend} />);

    await userEvent.type(screen.getByRole("textbox"), "Why this change?");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(onSend).toHaveBeenCalledWith({
      prompt: "Why this change?",
      attachments: [MARKER, OTHER],
    });
  });

  it("drops a chip when it is removed, and the turn no longer carries it", async () => {
    const onSend = vi.fn();
    render(<Composer attachments={[MARKER, OTHER]} onSend={onSend} />);

    const first = screen.getAllByRole("listitem")[0];
    await userEvent.click(within(first).getByRole("button", { name: /remove/i }));
    await userEvent.type(screen.getByRole("textbox"), "And this?");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.queryByText(/marker\.py/)).not.toBeInTheDocument();
    expect(onSend).toHaveBeenCalledWith({ prompt: "And this?", attachments: [OTHER] });
  });

  it("is disabled with the reason while a step runs", async () => {
    const onSend = vi.fn();
    render(
      <Composer
        attachments={[]}
        disabledReason="A step is running; its work is streamed here."
        onSend={onSend}
      />,
    );

    expect(screen.getByText(/a step is running/i)).toBeVisible();
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
    expect(onSend).not.toHaveBeenCalled();
  });
});
