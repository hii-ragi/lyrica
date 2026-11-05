import { numericSettings, booleanSettings, type ProcessingOptions } from "./processing";

const input = (key: string) => document.getElementById("setting-"+key) as HTMLInputElement;

export function createAdvancedSettings() {
  const root = document.getElementById("advanced-fields")!;
  const groups = new Map<string, HTMLElement>();
  function group(name: string) {
    if (!groups.has(name)) {
      const fieldset = document.createElement("fieldset");
      const legend = document.createElement("legend"); legend.textContent=name;
      fieldset.append(legend); root.append(fieldset); groups.set(name,fieldset);
    }
    return groups.get(name)!;
  }
  for (const [key, rule] of [...numericSettings, ...booleanSettings]) {
    const label = document.createElement("label");
    const title = document.createElement("span"); title.textContent = rule.label;
    const field = document.createElement("input"); field.id="setting-"+key;
    const help = document.createElement("small"); help.textContent=rule.help+" 標準: "+(typeof rule.default==="boolean" ? (rule.default ? "オン" : "オフ") : rule.default);
    if ("min" in rule) {
      help.textContent += "（範囲: "+rule.min+"〜"+rule.max+"）";
      field.type="number"; field.min=String(rule.min); field.max=String(rule.max); field.step=String(rule.step);
      field.value=String(rule.default);
    } else {
      field.type="checkbox"; field.checked=rule.default; label.classList.add("check-setting");
    }
    label.append(title,field,help); group(rule.group).append(label);
  }
}
export function readAdvancedSettings() {
  return Object.fromEntries([
    ...numericSettings.map(([key])=>[key,input(key).valueAsNumber]),
    ...booleanSettings.map(([key])=>[key,input(key).checked]),
  ]);
}
export function applyAdvancedSettings(options: ProcessingOptions) {
  for (const [key] of numericSettings) input(key).value=String(options[key]);
  for (const [key] of booleanSettings) input(key).checked=options[key];
  input("review_agreement").min=String(options.min_agreement);
}
export function advancedControls(locked: boolean, device: string, engine: string, separate: boolean) {
  for (const [key,rule] of numericSettings) {
    input(key).disabled=locked || (!!rule.device && rule.device!==device) || (!!rule.engine && rule.engine!==engine)
      || ((rule.group==="VAD" || key==="whisperx_chunk_seconds") && !input("vad_enabled").checked) || (rule.group==="ボーカル分離" && !separate);
  }
}
export function validSettings(report = false) {
  const min=input("min_agreement").valueAsNumber;
  input("review_agreement").min=String(Number.isFinite(min) ? min : .1);
  const invalid=Array.from(document.querySelectorAll<HTMLInputElement>(".options input"))
    .find(field=>!field.disabled && !field.checkValidity());
  if (invalid && report) {
    document.getElementById("advanced-settings")!.setAttribute("open","");
    invalid.reportValidity();
  }
  return !invalid;
}
