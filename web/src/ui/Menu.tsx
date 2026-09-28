import {
  createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode,
} from "react";

/* Все операции над приказом, пунктом, правилом и атрибутом собраны в одно
   выпадающее меню: иначе строка действий шире самого содержимого.
   Открыто не больше одного меню; прокрутка, ресайз, Escape и клик мимо
   закрывают его. */

export type MenuItem = { label: string; run: () => unknown; danger?: boolean } | null;

interface OpenMenu {
  anchor: DOMRect;
  items: MenuItem[];
}

const MenuContext = createContext<(anchor: HTMLElement, items: MenuItem[]) => void>(() => {});

export function MenuProvider({ children }: { children: ReactNode }) {
  const [menu, setMenu] = useState<OpenMenu | null>(null);
  const close = useCallback(() => setMenu(null), []);
  const open = useCallback((anchor: HTMLElement, items: MenuItem[]) =>
    setMenu({ anchor: anchor.getBoundingClientRect(), items }), []);

  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    addEventListener("scroll", close, true);
    addEventListener("resize", close);
    addEventListener("keydown", onKey);
    return () => {
      removeEventListener("scroll", close, true);
      removeEventListener("resize", close);
      removeEventListener("keydown", onKey);
    };
  }, [menu, close]);

  return (
    <MenuContext.Provider value={open}>
      {children}
      {menu && <Popup menu={menu} close={close} />}
    </MenuContext.Provider>
  );
}

function Popup({ menu, close }: { menu: OpenMenu; close: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: -9999, top: -9999 });

  // Меню прижато к правому краю кнопки и не выходит за экран;
  // если снизу не помещается — открывается вверх.
  useLayoutEffect(() => {
    const el = ref.current!;
    const { anchor } = menu;
    const width = el.offsetWidth;
    const height = el.offsetHeight;
    const below = anchor.bottom + 6;
    setPos({
      left: Math.max(8, Math.min(anchor.right - width, innerWidth - width - 8)),
      top: below + height > innerHeight - 8 ? Math.max(8, anchor.top - height - 6) : below,
    });
  }, [menu]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) close();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [close]);

  return (
    <div className="popup" role="menu" ref={ref} style={pos}>
      {menu.items.map((item, i) => item ? (
        <button key={item.label} role="menuitem" className={item.danger ? "danger" : ""}
          onClick={() => { close(); item.run(); }}>
          {item.label}
        </button>
      ) : <div key={"sep" + i} className="sep" />)}
    </div>
  );
}

export function MenuButton({ items }: { items: () => MenuItem[] }) {
  const open = useContext(MenuContext);
  return (
    <button className="btn sm menu-btn" title="Действия" aria-label="Действия"
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => { e.stopPropagation(); open(e.currentTarget, items()); }}>
      ⋯
    </button>
  );
}
