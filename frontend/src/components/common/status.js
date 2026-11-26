import { decisions, stages } from '../../constants/enums.js';
import { escapeHtml as e } from '../../utils/format.js';

export const status = value => `<span class="status s-${e(value)}">${e(stages[value] ?? decisions[value] ?? value)}</span>`;

export const obsoleteBadge = obsolete => obsolete ? '<span class="status s-obsolete" title="同批源数据已有新版本，本预审已失效；已签发的旧交接单仍可查阅">已失效</span>' : '';
