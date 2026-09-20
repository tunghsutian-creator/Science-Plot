// Adapted from Tavotto, AGPL-3.0-only. Upstream commit 4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186.
// See web/editor/THIRD_PARTY.md for source files, retained excerpts and modifications.
import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react'
import { cn } from './utils'
import { FIELD_BOX as BOX_CLASS, FIELD_DISABLED as BOX_DISABLED, FIELD_FOCUS as BOX_FOCUS, FIELD_FOCUS_WITHIN as BOX_FOCUS_WITHIN, FIELD_INVALID as BOX_INVALID } from './fieldBox'
const t = (key: string, args?: {label:string}) => key === 'colorField.picker' ? `选择${args?.label ?? '颜色'}` : '无颜色'
export interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** 校验不过：红边 + `aria-invalid`；错误文案由调用方用 `aria-describedby` 指过去 */
  invalid?: boolean
  /**
   * 框内后缀：`[ 393.7      mm ]`——单位坐在框里、靠右，与数字形成稳定结构，
   * 而不是 `[393.7] mm` 那样漂在框外。给了它输入文字自动右对齐（数字的读法）；
   * 要左对齐传 `align="left"`。
   */
  suffix?: ReactNode
  align?: 'left' | 'right'
}

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { className, invalid, suffix, align, disabled, ...props },
  ref,
) {
  const alignRight = align === 'right' || (align == null && suffix != null)
  if (suffix == null) {
    return (
      <input
        ref={ref}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        className={cn(
          'h-7 w-full min-w-0 px-2 placeholder:text-ink-3 outline-none',
          BOX_CLASS,
          BOX_FOCUS,
          alignRight && 'text-right tabular-nums',
          invalid && BOX_INVALID,
          disabled && BOX_DISABLED,
          className,
        )}
        {...props}
      />
    )
  }
  return (
    // 外壳是「框」，输入框透明：hover / focus 状态挂在外壳上，后缀也在框里
    <span
      className={cn(
        'flex h-7 w-full min-w-0 items-center',
        BOX_CLASS,
        BOX_FOCUS_WITHIN,
        invalid && BOX_INVALID,
        disabled && BOX_DISABLED,
        className,
      )}
    >
      <input
        ref={ref}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        className={cn(
          'h-full min-w-0 flex-1 bg-transparent pl-2 pr-1 text-inherit placeholder:text-ink-3 outline-none',
          alignRight && 'text-right tabular-nums',
        )}
        {...props}
      />
      <span className="shrink-0 select-none whitespace-nowrap pr-2 text-ink-3">{suffix}</span>
    </span>
  )
})
export const NO_COLOR = 'none'

export function ColorField({
  value,
  onChange,
  onGestureEnd,
  className,
  ariaLabel,
}: {
  value: string
  onChange: (v: string) => void
  /**
   * 这一轮取色结束（取色盘失焦）。取色是连续动作：系统取色盘拖着走会发一串
   * change，调用方靠它把整轮压成一条历史 + 一次定稿渲染。原生对话框不保证发
   * blur，所以调用方另有安静计时兜底——这里只管报告确实发生了的失焦。
   */
  onGestureEnd?: () => void
  className?: string
  /**
   * 无障碍名，**必填**。外面那行可见标签不是 `<label for>`，取色盘的名字只能
   * 显式给。2026-09-07 之前 18 个调用点一个都没给，读屏里它们全是「编辑文本」
   * （axe `label` critical）；类型必填才是不会烂掉的那种纪律。
   *
   * chromium 上一直是绿的，webkit（Windows）第一次跑就报出来：`input[type=color]`
   * 在那儿退化成普通文本框，axe 的 `label` 规则才落到它头上。
   */
  ariaLabel: string
}) {
  // 引擎报 `none` = 这条没有颜色（没设边色的形状、`fill` 关着的面、空心 marker），
  // 不是黑色（#427 之前 `to_hex` 丢掉 alpha，透明黑显示成 #000000，检查器摆出一条
  // 并不存在的黑边）。色块画成「无」：白底一道红斜线，与画布图形「无填充」同一个记号；
  // 取色盘本身只吃合法色号，喂它黑色当起点，用户一取色就是一个真的颜色。
  const none = value === NO_COLOR
  return (
    // 只剩一块色块（2026-09-11 用户反馈：去掉色号框，点色块取色）。
    // 取色盘是**透明盖在色块上的真控件**，自带一圈 focus ring——纯键盘 Tab 到它
    // 时屏幕上得有反馈；overflow-hidden 只裁子元素，不会吃掉这一层自己的 outline。
    // 当前色号走 title：鼠标悬停仍看得到精确值。
    <div className={cn('flex h-7 items-center', className)}>
      <div
        title={none ? t('colorField.none') : value.toUpperCase()}
        data-none={none || undefined}
        className="relative h-5 w-8 shrink-0 overflow-hidden rounded-sm border border-border transition-colors hover:border-border-strong has-[:focus-visible]:focus-ring"
      >
        {none ? (
          <div
            className="absolute inset-0 bg-white"
            style={{
              backgroundImage:
                'linear-gradient(to top right, transparent calc(50% - 0.75px), #d0342c calc(50% - 0.75px), #d0342c calc(50% + 0.75px), transparent calc(50% + 0.75px))',
            }}
          />
        ) : (
          <div className="absolute inset-0" style={{ background: value }} />
        )}
        <input
          type="color"
          value={none ? '#000000' : value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onGestureEnd}
          aria-label={t('colorField.picker', { label: ariaLabel })}
          className="absolute inset-0 opacity-0"
        />
      </div>
    </div>
  )
}
