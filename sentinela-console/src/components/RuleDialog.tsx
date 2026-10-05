import {
  Button,
  Callout,
  Dialog,
  Field,
  FormGrid,
  Input,
  Segmented,
  Select,
  Switch,
  TagInput,
  Textarea,
} from 'broto-ui';
import { FlaskConical } from 'lucide-react';
import { useEffect, useState } from 'react';
import { patternTest } from '../api/queries';
import type { Category, Rule, RuleKind, RuleSpec, Severity } from '../api/types';
import { useTeam } from '../lib/context';
import { CATEGORY, SEVERITY, SEVERITY_ORDER } from '../lib/labels';

const EMPTY: RuleSpec = {
  code: '',
  title: '',
  category: 'standards',
  severity: 'medium',
  kind: 'ai',
  instruction: '',
  pattern: '',
  ignore_case: false,
  paths: [],
  exclude_paths: [],
  suggestion: '',
  reference_url: '',
  enabled: true,
};

export function RuleDialog({
  open,
  rule,
  onClose,
  onSave,
  saving,
}: {
  open: boolean;
  rule: Rule | null;
  onClose: () => void;
  onSave: (spec: RuleSpec) => Promise<void>;
  saving: boolean;
}) {
  const { team } = useTeam();
  const [form, setForm] = useState<RuleSpec>(EMPTY);
  const [sample, setSample] = useState('');
  const [test, setTest] = useState<{ valid: boolean; error: string | null; matches: { line: number; text: string }[] } | null>(null);

  useEffect(() => {
    if (open) {
      setForm(rule ? { ...EMPTY, ...rule, pattern: rule.pattern ?? '', suggestion: rule.suggestion ?? '', reference_url: rule.reference_url ?? '' } : EMPTY);
      setTest(null);
      setSample('');
    }
  }, [open, rule]);

  const set = <K extends keyof RuleSpec>(key: K, value: RuleSpec[K]) => setForm((f) => ({ ...f, [key]: value }));
  const isPattern = form.kind === 'pattern';

  const runTest = async () => {
    if (!form.pattern) return;
    setTest(await patternTest(team.name, { pattern: form.pattern, sample, ignore_case: !!form.ignore_case }));
  };

  const submit = async () => {
    await onSave({
      ...form,
      code: form.code.trim().toUpperCase(),
      pattern: isPattern ? form.pattern : null,
      suggestion: form.suggestion?.trim() || null,
      reference_url: form.reference_url?.trim() || null,
    });
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={rule ? `Editar ${rule.code}` : 'Nova regra'}
      description="Regras de IA descrevem o que verificar em linguagem natural. Regras de padrão usam uma expressão regular nas linhas adicionadas: são instantâneas e não gastam IA."
      onSubmit={() => void submit()}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" loading={saving}>
            {rule ? 'Salvar' : 'Criar regra'}
          </Button>
        </>
      }
    >
      <div className="snt-stack">
        <Segmented<RuleKind>
          aria-label="Tipo da regra"
          value={form.kind}
          onChange={(v) => set('kind', v)}
          options={[
            { value: 'ai', label: 'Avaliada pela IA' },
            { value: 'pattern', label: 'Padrão (regex)' },
          ]}
        />
        <FormGrid>
          <Field label="Código" hint="Ex.: SEC-010, ARQ-002" required>
            <Input value={form.code} onChange={(e) => set('code', e.target.value)} className="snt-mono" />
          </Field>
          <Field label="Título" required>
            <Input value={form.title} onChange={(e) => set('title', e.target.value)} />
          </Field>
          <Field label="Categoria">
            <Select value={form.category} onChange={(e) => set('category', e.target.value as Category)}>
              {(Object.keys(CATEGORY) as Category[]).map((c) => (
                <option key={c} value={c}>
                  {CATEGORY[c]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Severidade" hint="Bloqueante e alta bloqueiam o merge até haver justificativa (ajustável por repositório)">
            <Select value={form.severity} onChange={(e) => set('severity', e.target.value as Severity)}>
              {SEVERITY_ORDER.map((s) => (
                <option key={s} value={s}>
                  {SEVERITY[s].label}
                </option>
              ))}
            </Select>
          </Field>
        </FormGrid>

        {isPattern ? (
          <>
            <Field label="Expressão regular" hint="Aplicada a cada linha adicionada do diff (sintaxe Python)" required>
              <Input value={form.pattern ?? ''} onChange={(e) => set('pattern', e.target.value)} className="snt-mono" />
            </Field>
            <Switch checked={!!form.ignore_case} onCheckedChange={(v) => set('ignore_case', v)} label="Ignorar maiúsculas e minúsculas" />
            <Field label="Explicação mostrada no apontamento">
              <Textarea rows={2} value={form.instruction} onChange={(e) => set('instruction', e.target.value)} />
            </Field>
            <Field label="Testar a expressão" hint="Cole um trecho de código; cada linha é testada">
              <Textarea code rows={4} value={sample} onChange={(e) => setSample(e.target.value)} />
            </Field>
            <div className="snt-inline">
              <Button size="sm" variant="secondary" icon={<FlaskConical size={14} />} onClick={() => void runTest()} disabled={!form.pattern || !sample}>
                Testar
              </Button>
              {test && !test.valid && <span className="snt-check-fail snt-small">{test.error}</span>}
              {test?.valid && (
                <span className="snt-small">
                  {test.matches.length
                    ? `Casou nas linhas ${test.matches.map((m) => m.line).join(', ')}`
                    : 'Nenhuma linha casou'}
                </span>
              )}
            </div>
          </>
        ) : (
          <Field
            label="O que verificar"
            hint="Escreva como para um revisor: o que é proibido ou obrigatório e por quê. A IA cita o código da regra em cada apontamento."
            required
          >
            <Textarea rows={5} value={form.instruction} onChange={(e) => set('instruction', e.target.value)} />
          </Field>
        )}

        <FormGrid>
          <Field label="Só nestes arquivos" hint="Globs; vazio = todos os arquivos do perfil">
            <TagInput value={form.paths ?? []} onChange={(v) => set('paths', v)} placeholder="src/**/*.py" />
          </Field>
          <Field label="Exceto" hint="Ex.: **/tests/**">
            <TagInput value={form.exclude_paths ?? []} onChange={(v) => set('exclude_paths', v)} placeholder="**/tests/**" />
          </Field>
        </FormGrid>
        <Field label="Como corrigir (opcional)">
          <Textarea rows={2} value={form.suggestion ?? ''} onChange={(e) => set('suggestion', e.target.value)} />
        </Field>
        <Field label="Link de referência (opcional)" hint="Página do padrão na wiki do time">
          <Input value={form.reference_url ?? ''} onChange={(e) => set('reference_url', e.target.value)} />
        </Field>
        <Switch checked={form.enabled !== false} onCheckedChange={(v) => set('enabled', v)} label="Regra ativa" />
        {form.kind === 'ai' && form.severity === 'blocker' && (
          <Callout tone="warning">
            Regras de IA bloqueantes podem travar merges por falso positivo. Considere “Alta” e use bloqueante para regras de padrão.
          </Callout>
        )}
      </div>
    </Dialog>
  );
}
