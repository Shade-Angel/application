import { RuleBuilderPanel } from '@/features/rule-builder/ui/RuleBuilderPanel';
import { RulesList } from '@/widgets/rules-list/ui/RulesList';

export const RulesPage = () => (
  <div className="grid">
    <RuleBuilderPanel />
    <RulesList />
  </div>
);