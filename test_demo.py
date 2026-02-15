# %%
import sys

a = []
b = 1
c = {}
print(sys.getsizeof(a))
print(sys.getsizeof(b))
print(sys.getsizeof(c))


# %%
def new_func():
    print("Hello from WSL!")
    for i in range(10):
        pass

    print("Hello from WSL! im an other")


new_func()
# %%
x = 10


def my_func():
    x = 20
    print(x)  # 你以为会打印 10
    # 但因为这一行赋值，Python 会在编译阶段把 x 标记为“局部变量”


my_func()
# 报错：UnboundLocalError: local variable 'x' referenced before assignment


# %%
def count_to_three():
    yield 1
    yield 2
    yield 3


a = count_to_three()
b = next(a)
print(b)
b = next(a)
print(b)
b = next(a)
print(b)
b = next(a)
print(b)


# %%
def create_multipliers():
    return [lambda x: i * x for i in range(5)]


multipliers = create_multipliers()

# 我们预想输出 0, 2, 4, 6, 8
print([m(2) for m in multipliers])
# %%
name = ["username", "email"]
a = ["zhangsan", "aaa@111"]
data = []
c = dict(zip(name, a))
data.append(c)
print(c)
print(data)
print(c.items())

# %%
print("1")
# %%
