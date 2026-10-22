/* eslint-disable @next/next/no-img-element -- tiny static brand marks; next/image adds nothing here */

export type BrandId = "twilio" | "retell" | "elevenlabs" | "openai" | "whisper" | "sarvam";

const BRANDS: Record<BrandId, { src: string; name: string; bg: string; pad: string }> = {
  twilio: { src: "/brands/twilio.svg", name: "Twilio", bg: "bg-rose-50", pad: "p-1.5" },
  retell: { src: "/brands/retell.png", name: "Retell AI", bg: "bg-white", pad: "p-0.5" },
  elevenlabs: { src: "/brands/elevenlabs.svg", name: "ElevenLabs", bg: "bg-zinc-100", pad: "p-2" },
  openai: { src: "/brands/openai.svg", name: "OpenAI", bg: "bg-white", pad: "p-1.5" },
  whisper: { src: "/brands/openai.svg", name: "OpenAI Whisper", bg: "bg-emerald-50", pad: "p-1.5" },
  sarvam: { src: "/brands/sarvam.svg", name: "Sarvam AI", bg: "bg-orange-50", pad: "p-1.5" },
};

export function isBrand(id: string): id is BrandId {
  return id in BRANDS;
}

/** Official brand mark in a rounded tile. Sizes: sm (24px), md (40px), lg (48px). */
export function ProviderLogo({ id, size = "md", className = "" }: { id: BrandId; size?: "xs" | "sm" | "md" | "lg"; className?: string }) {
  const b = BRANDS[id];
  const dims = { xs: "h-5 w-5 rounded-md", sm: "h-7 w-7 rounded-lg", md: "h-10 w-10 rounded-xl", lg: "h-12 w-12 rounded-2xl" }[size];
  return (
    <span className={`grid shrink-0 place-items-center overflow-hidden ring-1 ring-black/5 ${b.bg} ${dims} ${size === "xs" ? "p-0.5" : b.pad} ${className}`}>
      <img src={b.src} alt={b.name} className="h-full w-full object-contain" draggable={false} />
    </span>
  );
}

export function brandName(id: string) {
  return isBrand(id) ? BRANDS[id].name : id;
}
