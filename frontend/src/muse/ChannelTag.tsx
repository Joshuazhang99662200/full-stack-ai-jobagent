import type { CSSProperties, MouseEvent } from "react";

// 渠道标签 — the ONE shared channel badge for the whole panel.
//
// Every place that shows a channel name renders this component
// instead of styling its own copy: the job list's 渠道 column, the
// detail dialog, the greeting review view, the todo dialog, the
// execution list, and the login-restore entries. Changing a brand
// color happens here once and applies everywhere.
//
// Brand colors with white bold text (user instruction 2026-11-02):
// 猎聘 logo orange, BOSS blue-green (teal), 智联 blue. A channel
// with no known brand color keeps the plain bordered chip.
const CHANNEL_BRAND_COLORS: [needle: string, color: string][] = [
  ["猎聘", "#ff6000"],
  ["BOSS", "#00a8a0"],
  ["智联", "#2e5bff"],
];

export function channelBrandColor(channel: string): string | null {
  for (const [needle, color] of CHANNEL_BRAND_COLORS) {
    if (channel.includes(needle)) return color;
  }
  return null;
}

export function ChannelTag({
  channel,
  onClick,
  ariaLabel,
}: {
  channel: string;
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void;
  ariaLabel?: string;
}) {
  const brand = channelBrandColor(channel);
  const style: CSSProperties | undefined = brand
    ? {
        backgroundColor: brand,
        borderColor: brand,
        color: "#ffffff",
        fontWeight: 600,
      }
    : undefined;
  const cls = "chan";
  if (onClick) {
    return (
      <button
        data-channel={channel}
        type="button"
        aria-label={ariaLabel}
        className={`${cls} focus:outline-none focus:ring-2 focus:ring-[var(--accent)]`}
        style={style}
        onClick={onClick}
      >
        {channel}
      </button>
    );
  }
  return (
    <span data-channel={channel} className={cls} style={style}>
      {channel}
    </span>
  );
}
