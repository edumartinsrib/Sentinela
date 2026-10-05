import { BoxMark, Brand } from 'broto-ui';

/** Portão com um ponto de passagem, no box da identidade (viewBox 32×32). */
export function GateGlyph() {
  return (
    <g>
      <path d="M10 23V11.5M22 23V11.5M10 15h12" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" fill="none" />
      <circle cx="16" cy="20.5" r="1.9" fill="#fff" />
    </g>
  );
}

export function SentinelaMark({ size = 30 }: { size?: number }) {
  return <BoxMark size={size} glyph={<GateGlyph />} title="Sentinela" />;
}

export function SentinelaBrand({ tone, size }: { tone?: 'light' | 'dark'; size?: number }) {
  return <Brand name="Sentinela" tone={tone} mark={<SentinelaMark size={size ?? 30} />} />;
}
